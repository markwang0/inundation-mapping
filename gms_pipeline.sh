#!/bin/bash -e
:
usage ()
{
    echo
    echo 'Produce GMS hydrofabric datasets for unit and branch scale.'
    echo 'Usage : gms_pipeline.sh [REQ: -u <hucs> -n <run name> ]'
    echo '                        [OPT: -h -c <config file> -j <job limit>] -o'
    echo '                         -ud <unit deny list file>'
    echo '                         -bd <branch deny list file>'
    echo '                         -zd <branch zero deny list file>]'
    echo ''
    echo 'REQUIRED:'
    echo '  -u/--hucList    : HUC8s to run or multiple passed in quotes (space delimited) file.'
    echo '                    A line delimited file is also acceptable. HUCs must present in inputs directory.'
    echo '  -n/--runName    : a name to tag the output directories and log files as. could be a version tag.'
    echo 
    echo 'OPTIONS:'
    echo '  -h/--help       : help file'
    echo '  -c/--config     : configuration file with bash environment variables to export'
    echo '                    Default (if arg not added) : /foss_fim/config/params_template.env'    
    echo '  -ud/--unitDenylist : A file with a line delimited list of files in UNIT (HUC) directories to be removed'
    echo '                    upon completion (see config/deny_gms_unit_prod.lst for a starting point)'
    echo '                    Default (if arg not added) : /foss_fim/config/deny_gms_unit_prod.lst'
    echo '                    -- Note: if you want to keep all output files (aka.. no files removed),'
    echo '                    use the word NONE as this value for this parameter.'
    echo '  -bd/--branchDenylist : A file with a line delimited list of files in BRANCHES directories to be removed' 
    echo '                    upon completion of branch processing.'
    echo '                    (see config/deny_gms_branches_prod.lst for a starting point)'
    echo '                    Default: /foss_fim/config/deny_gms_branches_prod.lst'   
    echo '                    -- Note: if you want to keep all output files (aka.. no files removed),'
    echo '                    use the word NONE as this value for this parameter.'
    echo '  -zd/--branchZeroDenylist : A file with a line delimited list of files in BRANCH ZERO directories to' 
    echo '                    be removed upon completion of branch zero processing.'
    echo '                    (see config/deny_gms_branch_zero.lst for a starting point)'
    echo '                    Default: /foss_fim/config/deny_gms_branch_zero.lst'   
    echo '                    -- Note: if you want to keep all output files (aka.. no files removed),'
    echo '                    use the word NONE as this value for this parameter.'    
    echo '  -j/--jobLimit   : max number of concurrent jobs to run. Default 1 job at time.'
    echo '                    stdout and stderr to terminal and logs. With >1 outputs progress and logs the rest'
    echo '  -o/--overwrite  : overwrite outputs if already exist'
    echo
    exit
}

set -e

while [ "$1" != "" ]; do
case $1
in
    -u|--hucList)
        shift
        hucList=$1
        ;;
    -c|--configFile )
        shift
        envFile=$1
        ;;
    -n|--runName)
        shift
        runName=$1
        ;;
    -j|--jobLimit)
        shift
        jobLimit=$1
        ;;
    -h|--help)
        shift
        usage
        ;;
    -o|--overwrite)
        overwrite=1
        ;;
    -ud|--unitDenylist)
        shift
        deny_unit_list=$1
        ;;
    -bd|--branchDenylist)
        shift
        deny_branches_list=$1
        ;;
    -zd|--branchZeroDenylist)
        shift
        deny_branch_zero_list=$1
        ;;        
    *) ;;
    esac
    shift
done

# print usage if arguments empty
if [ "$hucList" = "" ]
then
    echo "ERROR: Missing -u Huclist argument"
    usage
fi
if [ "$runName" = "" ]
then
    echo "ERROR: Missing -n run time name argument"
    usage
fi

if [ "$envFile" = "" ]
then
    envFile=/foss_fim/config/params_template.env
fi

if [ -z "$overwrite" ]
then
    # default is false (0)
    overwrite=0
fi

# The tests for the deny lists are duplicated here on to help catch
# them earlier (ie.. don't have to wait to process units to find an
# pathing error with the branch deny list)
if [ "$deny_unit_list" != "" ] && \
   [ "${deny_unit_list^^}" != "NONE" ] && \
   [ ! -f "$deny_unit_list" ]
then
    # NONE is not case sensitive
    echo "Error: The -ud <unit deny file> does not exist and is not the word NONE"
    usage
fi

if [ "$deny_branches_list" != "" ] && \
   [ "${deny_branches_list^^}" != "NONE" ] && \
   [ ! -f "$deny_branches_list" ]
then
    # NONE is not case sensitive
    echo "Error: The -bd <branch deny file> does not exist and is not the word NONE"
    usage
fi

if [ "$deny_branch_zero_list" != "" ] && \
   [ "${deny_branch_zero_list^^}" != "NONE" ] && \
   [ ! -f "$deny_branch_zero_list" ]
then
    echo "Error: The -zd <branch zero deny file> does not exist and is not the word NONE"
    usage
fi

## SOURCE ENV FILE AND FUNCTIONS ##
source $envFile
source $srcDir/bash_functions.env

# default values
if [ "$jobLimit" = "" ] ; then
    jobLimit=$default_max_jobs
fi

export outputRunDataDir=$outputDataDir/$runName

if [ -d $outputRunDataDir ] && [ $overwrite -eq 0 ]; then
    echo
    echo "ERROR: Output dir $outputRunDataDir exists. Use overwrite -o to run."
    echo        
    usage
fi

pipeline_start_time=`date +%s`

num_hucs=$(python3 $srcDir/check_huc_inputs.py -u $hucList)

echo
echo "======================= Start of gms_pipeline.sh ========================="
echo "Number of HUCs to process is $num_hucs"

## Produce gms hydrofabric at unit level first (gms_run_unit)

# We have to build this as a string as some args are optional.
# but the huclist doesn't always pass well, so just worry about
# the rest of the params.
run_cmd=" -n $runName"
run_cmd+=" -c $envFile"
run_cmd+=" -j $jobLimit"

if [ $overwrite -eq 1 ]; then run_cmd+=" -o" ; fi

#echo "$run_cmd"
. /foss_fim/gms_run_unit.sh -u "$hucList" $run_cmd -ud "$deny_unit_list" -zd "$deny_branch_zero_list"

## CHECK IF OK TO CONTINUE ON TO BRANCH STEPS
# Count the number of files in the $outputRunDataDir/unit_errors
# If no errors, there will be only one file, non_zero_exit_codes.log.
# Calculate the number of error files as a percent of the number of hucs 
# originally submitted. If the percent error is over "x" threshold stop processing
# Note: This applys only if there are a min number of hucs. Aka.. if min threshold
# is set to 10, then only return a sys.exit of > 1, if there is at least 10 errors

# if this has too many errors, it will return a sys.exit code (like 62 as per fim_enums)
# and we will stop the rest of the process. We have to catch stnerr as well.
# This stops the run from continuing to run, drastically filing drive and killing disk space.
python3 $srcDir/check_unit_errors.py -f $outputRunDataDir -n $num_hucs

## Produce level path or branch level datasets
. /foss_fim/gms_run_branch.sh $run_cmd -bd "$deny_branches_list" -zd "$deny_branch_zero_list"


## continue on to post processing
. /foss_fim/gms_run_post_processing.sh $run_cmd

echo
echo "======================== End of gms_pipeline.sh =========================="
date -u
Calc_Duration $pipeline_start_time
echo

