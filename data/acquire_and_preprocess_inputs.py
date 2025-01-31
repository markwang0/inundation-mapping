#!/usr/bin/env python3

import os
import argparse
import csv
import sys
sys.path.append('/foss_fim/src')
import shutil
from multiprocessing import Pool
import geopandas as gpd
from urllib.error import HTTPError
from tqdm import tqdm

from utils.shared_variables import (NHD_URL_PARENT,
                                    NHD_URL_PREFIX,
                                    NHD_RASTER_URL_SUFFIX,
                                    NHD_VECTOR_URL_SUFFIX,
                                    NHD_VECTOR_EXTRACTION_PREFIX,
                                    NHD_VECTOR_EXTRACTION_SUFFIX,
                                    PREP_PROJECTION,
                                    WBD_NATIONAL_URL,
                                    FIM_ID,
                                    OVERWRITE_WBD,
                                    OVERWRITE_NHD,
                                    OVERWRITE_ALL,
                                    nhd_raster_url_template,
                                    nhd_vector_url_template
                                    )

from utils.shared_functions import (pull_file, run_system_command,
                                    subset_wbd_gpkg, delete_file,
                                    getDriver)

NHDPLUS_VECTORS_DIRNAME = 'nhdplus_vectors'
NHDPLUS_RASTERS_DIRNAME = 'nhdplus_rasters'
NWM_HYDROFABRIC_DIRNAME = 'nwm_hydrofabric'
NWM_FILE_TO_SUBSET_WITH = 'nwm_flows.gpkg'

def subset_wbd_to_nwm_domain(wbd,nwm_file_to_use):

    intersecting_indices = [not (gpd.read_file(nwm_file_to_use,mask=b).empty) for b in wbd.geometry]

    return(wbd[intersecting_indices])

def pull_and_prepare_wbd(path_to_saved_data_parent_dir,nwm_dir_name,nwm_file_to_use,overwrite_wbd,num_workers):
    """
    This helper function pulls and unzips Watershed Boundary Dataset (WBD) data. It uses the WBD URL defined by WBD_NATIONAL_URL.
    This function also subsets the WBD layers (HU4, HU6, HU8) to CONUS and converts to geopkacage layers.

    Args:
        path_to_saved_data_parent_dir (str): The system path to where the WBD will be downloaded, unzipped, and preprocessed.

    """

    # Construct path to wbd_directory and create if not existent.
    wbd_directory = os.path.join(path_to_saved_data_parent_dir, 'wbd')
    if not os.path.exists(wbd_directory):
        os.mkdir(wbd_directory)

    wbd_gdb_path = os.path.join(wbd_directory, 'WBD_National_GDB.gdb')
    pulled_wbd_zipped_path = os.path.join(wbd_directory, 'WBD_National_GDB.zip')

    multilayer_wbd_geopackage = os.path.join(wbd_directory, 'WBD_National.gpkg')

    nwm_huc_list_file_template = os.path.join(wbd_directory,'nwm_wbd{}.csv')

    nwm_file_to_use = os.path.join(path_to_saved_data_parent_dir,nwm_dir_name,nwm_file_to_use)
    if not os.path.isfile(nwm_file_to_use):
        raise IOError("NWM File to Subset Too Not Available: {}".format(nwm_file_to_use))

    if not os.path.exists(multilayer_wbd_geopackage) or overwrite_wbd:
        # Download WBD and unzip if it's not already done.
        if not os.path.exists(wbd_gdb_path):
            if not os.path.exists(pulled_wbd_zipped_path):
                pull_file(WBD_NATIONAL_URL, pulled_wbd_zipped_path)
            os.system("7za x {pulled_wbd_zipped_path} -o{wbd_directory}".format(pulled_wbd_zipped_path=pulled_wbd_zipped_path, wbd_directory=wbd_directory))

        procs_list, wbd_gpkg_list = [], []
        multilayer_wbd_geopackage = os.path.join(wbd_directory, 'WBD_National.gpkg')
        # Add fimid to HU8, project, and convert to geopackage.
        if os.path.isfile(multilayer_wbd_geopackage):
            os.remove(multilayer_wbd_geopackage)
        print("Making National WBD GPKG...")
        print("\tWBDHU8")
        wbd_hu8 = gpd.read_file(wbd_gdb_path, layer='WBDHU8')
        wbd_hu8 = wbd_hu8.rename(columns={'huc8':'HUC8'}) # rename column to caps
        wbd_hu8 = wbd_hu8.sort_values('HUC8')
        fimids = [str(item).zfill(4) for item in list(range(1000, 1000 + len(wbd_hu8)))]
        wbd_hu8[FIM_ID] = fimids
        wbd_hu8 = wbd_hu8.to_crs(PREP_PROJECTION)  # Project.
        wbd_hu8 = subset_wbd_to_nwm_domain(wbd_hu8,nwm_file_to_use)
        wbd_hu8.geometry = wbd_hu8.buffer(0)
        wbd_hu8.to_file(multilayer_wbd_geopackage,layer='WBDHU8',driver=getDriver(multilayer_wbd_geopackage),index=False)  # Save.
        wbd_hu8.HUC8.to_csv(nwm_huc_list_file_template.format('8'),index=False,header=False)
        #wbd_gpkg_list.append(os.path.join(wbd_directory, 'WBDHU8.gpkg'))  # Append to wbd_gpkg_list for subsetting later.
        del wbd_hu8

        # Prepare procs_list for multiprocessed geopackaging.
        for wbd_layer_num in ['4', '6']:
            wbd_layer = 'WBDHU' + wbd_layer_num
            print("\t{}".format(wbd_layer))
            wbd = gpd.read_file(wbd_gdb_path,layer=wbd_layer)
            wbd = wbd.to_crs(PREP_PROJECTION)
            wbd = wbd.rename(columns={'huc'+wbd_layer_num : 'HUC' + wbd_layer_num})
            wbd = subset_wbd_to_nwm_domain(wbd,nwm_file_to_use)
            wbd.geometry = wbd.buffer(0)
            wbd.to_file(multilayer_wbd_geopackage,layer=wbd_layer,driver=getDriver(multilayer_wbd_geopackage),index=False)
            wbd['HUC{}'.format(wbd_layer_num)].to_csv(nwm_huc_list_file_template.format(wbd_layer_num),index=False,header=False)
            #output_gpkg = os.path.join(wbd_directory, wbd_layer + '.gpkg')
            #wbd_gpkg_list.append(output_gpkg)
            #procs_list.append(['ogr2ogr -overwrite -progress -f GPKG -t_srs "{projection}" {output_gpkg} {wbd_gdb_path} {wbd_layer}'.format(output_gpkg=output_gpkg, wbd_gdb_path=wbd_gdb_path, wbd_layer=wbd_layer, projection=PREP_PROJECTION)])

        # with Pool(processes=num_workers) as pool:
            # pool.map(run_system_command, procs_list)

        # Subset WBD layers to CONUS and add to single geopackage.
        #print("Subsetting WBD layers to CONUS...")
        #multilayer_wbd_geopackage = os.path.join(wbd_directory, 'WBD_National.gpkg')
        #for gpkg in wbd_gpkg_list:
        #    subset_wbd_gpkg(gpkg, multilayer_wbd_geopackage)

    # Clean up temporary files.
    #for temp_layer in ['WBDHU4', 'WBDHU6', 'WBDHU8']:
    #    delete_file(os.path.join(wbd_directory, temp_layer + '.gpkg'))
    #pulled_wbd_zipped_path = os.path.join(wbd_directory, 'WBD_National_GDB.zip')
    #delete_file(pulled_wbd_zipped_path)
    #delete_file(os.path.join(wbd_directory, 'WBD_National_GDB.jpg'))

    return(wbd_directory)

def pull_and_prepare_nwm_hydrofabric(path_to_saved_data_parent_dir, path_to_preinputs_dir,num_workers):
    """
    This helper function pulls and unzips NWM hydrofabric data. It uses the NWM hydrofabric URL defined by NWM_HYDROFABRIC_URL.

    Args:
        path_to_saved_data_parent_dir (str): The system path to where a 'nwm' subdirectory will be created and where NWM hydrofabric
        will be downloaded, unzipped, and preprocessed.

    """

    # -- Acquire and preprocess NWM data -- #
    nwm_hydrofabric_directory = os.path.join(path_to_saved_data_parent_dir, 'nwm_hydrofabric')
    if not os.path.exists(nwm_hydrofabric_directory):
        os.mkdir(nwm_hydrofabric_directory)

    nwm_hydrofabric_gdb = os.path.join(path_to_preinputs_dir, 'nwm_v21.gdb')

    # Project and convert to geopackage.
    print("Projecting and converting NWM layers to geopackage...")
    procs_list = []
    for nwm_layer in ['nwm_flows', 'nwm_lakes', 'nwm_catchments']:  # I had to project the catchments and waterbodies because these 3 layers had varying CRSs.
        print("Operating on " + nwm_layer)
        output_gpkg = os.path.join(nwm_hydrofabric_directory, nwm_layer + '_proj.gpkg')
        procs_list.append(['ogr2ogr -overwrite -progress -f GPKG -t_srs "{projection}" {output_gpkg} {nwm_hydrofabric_gdb} {nwm_layer}'.format(projection=PREP_PROJECTION, output_gpkg=output_gpkg, nwm_hydrofabric_gdb=nwm_hydrofabric_gdb, nwm_layer=nwm_layer)])

    with Pool(processes=num_workers) as pool:
        pool.map(run_system_command, procs_list)


def pull_and_prepare_nhd_data(nhd_raster_download_url,
                              nhd_raster_extraction_path,
                              nhd_vector_download_url,
                              nhd_vector_extraction_path,
                              overwrite_nhd_dem,
                              overwrite_nhd_gdb
                             ):
    """
    This helper function is designed to be multiprocessed. It pulls and unzips NHD raster and vector data.
    Args:
        args (list): A list of arguments in this format: [nhd_raster_download_url, nhd_raster_extraction_path, nhd_vector_download_url, nhd_vector_extraction_path]
    """
    # Update extraction path from .zip to .gdb
    nhd_gdb = nhd_vector_extraction_path.replace('.zip', '.gdb')

    # Download raster and vector, if not already in user's directory (exist check performed by pull_file()).
    nhd_raster_extraction_parent = os.path.dirname(nhd_raster_extraction_path)
    huc = os.path.basename(nhd_raster_extraction_path).split('_')[2]

    nhd_raster_parent_dir = os.path.join(nhd_raster_extraction_parent, 'HRNHDPlusRasters' + huc)

    if not os.path.exists(nhd_raster_parent_dir):
        os.mkdir(nhd_raster_parent_dir)

    elev_cm_tif = os.path.join(nhd_raster_parent_dir, 'elev_cm.tif')
    elev_m_tif = os.path.join(nhd_raster_parent_dir, 'elev_m.tif')
    if not os.path.exists(elev_cm_tif) or overwrite_nhd_dem:
        pull_file(nhd_raster_download_url, nhd_raster_extraction_path)
        os.system("7za e {nhd_raster_extraction_path} -o{nhd_raster_parent_dir} elev_cm.tif -r ".format(nhd_raster_extraction_path=nhd_raster_extraction_path, nhd_raster_parent_dir=nhd_raster_parent_dir))

        file_list = os.listdir(nhd_raster_parent_dir)
        for f in file_list:
            full_path = os.path.join(nhd_raster_parent_dir, f)
            if 'elev_cm' not in f:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                elif os.path.isfile(full_path):
                    os.remove(full_path)
        os.remove(nhd_raster_extraction_path)

    nhd_vector_extraction_parent = os.path.dirname(nhd_vector_extraction_path)

    if not os.path.exists(nhd_vector_extraction_parent):
        os.mkdir(nhd_vector_extraction_parent)

    if not os.path.exists(nhd_gdb) or overwrite_nhd_gdb:  # Only pull if not already pulled and processed.
        # Download and fully unzip downloaded GDB.
        pull_file(nhd_vector_download_url, nhd_vector_extraction_path)
        huc = os.path.split(nhd_vector_extraction_parent)[1]  # Parse HUC.
        os.system("7za x {nhd_vector_extraction_path} -o{nhd_vector_extraction_parent}".format(nhd_vector_extraction_path=nhd_vector_extraction_path, nhd_vector_extraction_parent=nhd_vector_extraction_parent))
        # extract input stream network
        nhd = gpd.read_file(nhd_gdb,layer='NHDPlusBurnLineEvent')
        nhd = nhd.to_crs(PREP_PROJECTION)
        nhd.to_file(os.path.join(nhd_vector_extraction_parent, 'NHDPlusBurnLineEvent' + huc + '.gpkg'),driver='GPKG')
        # extract flowlines for FType attributes
        nhd = gpd.read_file(nhd_gdb,layer='NHDFlowline')
        nhd = nhd.to_crs(PREP_PROJECTION)
        nhd.to_file(os.path.join(nhd_vector_extraction_parent, 'NHDFlowline' + huc + '.gpkg'),driver='GPKG')
        # extract attributes
        nhd = gpd.read_file(nhd_gdb,layer='NHDPlusFlowLineVAA')
        nhd.to_file(os.path.join(nhd_vector_extraction_parent, 'NHDPlusFlowLineVAA' + huc + '.gpkg'),driver='GPKG')
        # -- Project and convert NHDPlusBurnLineEvent and NHDPlusFlowLineVAA vectors to geopackage -- #
        #for nhd_layer in ['NHDPlusBurnLineEvent', 'NHDPlusFlowlineVAA']:
        #    run_system_command(['ogr2ogr -overwrite -progress -f GPKG -t_srs "{projection}" {output_gpkg} {nhd_gdb} {nhd_layer}'.format(projection=PREP_PROJECTION, output_gpkg=output_gpkg, nhd_gdb=nhd_gdb, nhd_layer=nhd_layer)])  # Use list because function is configured for multiprocessing.
    # Delete unnecessary files.
    delete_file(nhd_vector_extraction_path.replace('.zip', '.jpg'))
    delete_file(nhd_vector_extraction_path)  # Delete the zipped GDB.


def build_huc_list_files(path_to_saved_data_parent_dir, wbd_directory):
    """
    This function builds a list of available HUC4s, HUC6s, and HUC8s and saves the lists to .lst files.

    Args:
        path_to_saved_data_parent_dir (str): The path to the parent directory where the .lst files will be saved.
        wbd_directory (str): The path to the directory storing the WBD geopackages which are used to determine which HUCs are available for processing.

    """

    print("Building included HUC lists...")
    # Identify all saved NHDPlus Vectors.
    nhd_plus_raster_dir = os.path.join(path_to_saved_data_parent_dir, NHDPLUS_RASTERS_DIRNAME)
    nhd_plus_vector_dir = os.path.join(path_to_saved_data_parent_dir, NHDPLUS_VECTORS_DIRNAME)

    huc4_list = [i[-4:] for i in os.listdir(nhd_plus_raster_dir)]
    huc6_list, huc8_list = [], []

    # Read WBD into dataframe.
    full_huc_gpkg = os.path.join(wbd_directory, 'WBD_National.gpkg')
    huc_gpkg = 'WBDHU8' # The WBDHU4 are handled by the nhd_plus_raster_dir name.

    # Open geopackage.
    wbd = gpd.read_file(full_huc_gpkg, layer=huc_gpkg)

    # Loop through entries and compare against the huc4_list to get available HUCs within the geopackage domain.
    for index, row in tqdm(wbd.iterrows(),total=len(wbd)):
        huc = row["HUC" + huc_gpkg[-1]]
        huc_mask = wbd.loc[wbd[str("HUC" + huc_gpkg[-1])]==huc].geometry
        burnline = os.path.join(nhd_plus_vector_dir, huc[0:4], 'NHDPlusBurnLineEvent' + huc[0:4] + '.gpkg')
        if os.path.exists(burnline):
            nhd_test = len(gpd.read_file(burnline, mask = huc_mask)) # this is slow, iterates through 2000+ HUC8s
            # Append huc to huc8 list.
            if (str(huc[:4]) in huc4_list) & (nhd_test>0):
                huc8_list.append(huc)

    huc6_list = [w[:6] for w in huc8_list]
    huc6_list = set(huc6_list)

    # Write huc lists to appropriate .lst files.
    huc_lists_dir = os.path.join(path_to_saved_data_parent_dir, 'huc_lists')
    if not os.path.exists(huc_lists_dir):
        os.mkdir(huc_lists_dir)
    included_huc4_file = os.path.join(huc_lists_dir, 'included_huc4.lst')
    included_huc6_file = os.path.join(huc_lists_dir, 'included_huc6.lst')
    included_huc8_file = os.path.join(huc_lists_dir, 'included_huc8.lst')

    # Overly verbose file writing loops. Doing this in a pinch.
    with open(included_huc4_file, 'w') as f:
        for item in huc4_list:
            f.write("%s\n" % item)

    with open(included_huc6_file, 'w') as f:
        for item in huc6_list:
            f.write("%s\n" % item)

    with open(included_huc8_file, 'w') as f:
        for item in huc8_list:
            f.write("%s\n" % item)


def manage_preprocessing( hucs_of_interest,
                          num_workers=1,
                          overwrite_nhd_dem=False,
                          overwrite_nhd_gdb=False,
                          overwrite_wbd=False
                        ):
    """
    This functions manages the downloading and preprocessing of gridded and vector data for FIM production.

    Args:
        hucs_of_interest (str): Path to a user-supplied config file of hydrologic unit codes to be pulled and post-processed.

    """

    #get input data dir
    path_to_saved_data_parent_dir = os.environ['inputDataDir']

    nhd_procs_list = []  # Initialize procs_list for multiprocessing.

    # Create the parent directory if nonexistent.
    if not os.path.exists(path_to_saved_data_parent_dir):
        os.mkdir(path_to_saved_data_parent_dir)

    # Create NHDPlus raster parent directory if nonexistent.
    nhd_raster_dir = os.path.join(path_to_saved_data_parent_dir, NHDPLUS_RASTERS_DIRNAME)
    if not os.path.exists(nhd_raster_dir):
        os.mkdir(nhd_raster_dir)

    # Create the vector data parent directory if nonexistent.
    vector_data_dir = os.path.join(path_to_saved_data_parent_dir, NHDPLUS_VECTORS_DIRNAME)
    if not os.path.exists(vector_data_dir):
        os.mkdir(vector_data_dir)

    # Parse HUCs from hucs_of_interest.
    if isinstance(hucs_of_interest,list):
        if len(hucs_of_interest) == 1:
            try:
                with open(hucs_of_interest[0]) as csv_file:  # Does not have to be CSV format.
                    huc_list = [i[0] for i in csv.reader(csv_file)]
            except FileNotFoundError:
                huc_list = hucs_of_interest
        else:
                huc_list = hucs_of_interest
    elif isinstance(hucs_of_interest,str):
        try:
            with open(hucs_of_interest) as csv_file:  # Does not have to be CSV format.
                huc_list = [i[0] for i in csv.reader(csv_file)]
        except FileNotFoundError:
            huc_list = list(hucs_of_interest)

    # get unique huc4s
    huc_list = [h[0:4] for h in huc_list]
    huc_list = list( set(huc_list) )

    # Construct paths to data to download and append to procs_list for multiprocessed pull, project, and converstion to geopackage.
    for huc in huc_list:
        huc = str(huc)  # Ensure huc is string.

        # Construct URL and extraction path for NHDPlus raster.
        #nhd_raster_download_url = os.path.join(NHD_URL_PARENT, NHD_URL_PREFIX + huc + NHD_RASTER_URL_SUFFIX)
        nhd_raster_download_url = nhd_raster_url_template.format(huc) 
        nhd_raster_extraction_path = os.path.join(nhd_raster_dir, NHD_URL_PREFIX + huc + NHD_RASTER_URL_SUFFIX)
        
        # Construct URL and extraction path for NHDPlus vector. Organize into huc-level subdirectories.
        #nhd_vector_download_url = os.path.join(NHD_URL_PARENT, NHD_URL_PREFIX + huc + NHD_VECTOR_URL_SUFFIX)
        nhd_vector_download_url = nhd_vector_url_template.format(huc) 
        nhd_vector_download_parent = os.path.join(vector_data_dir, huc)
        if not os.path.exists(nhd_vector_download_parent):
            os.mkdir(nhd_vector_download_parent)
        nhd_vector_extraction_path = os.path.join(nhd_vector_download_parent, NHD_VECTOR_EXTRACTION_PREFIX + huc + NHD_VECTOR_EXTRACTION_SUFFIX)

        # Append extraction instructions to nhd_procs_list.
        nhd_procs_list.append([nhd_raster_download_url, nhd_raster_extraction_path, nhd_vector_download_url, nhd_vector_extraction_path, overwrite_nhd_dem, overwrite_nhd_gdb])

    # Pull and prepare NHD data.
    # with Pool(processes=num_workers) as pool:
        # pool.map(pull_and_prepare_nhd_data, nhd_procs_list)

    for huc in nhd_procs_list:
        try:
            pull_and_prepare_nhd_data(*huc)
        except HTTPError:
            print("404 error for HUC4 {}".format(huc))

    # Pull and prepare NWM data.
    #pull_and_prepare_nwm_hydrofabric(path_to_saved_data_parent_dir, path_to_preinputs_dir,num_workers)  # Commented out for now.

    # Pull and prepare WBD data.
    wbd_directory = pull_and_prepare_wbd(path_to_saved_data_parent_dir,NWM_HYDROFABRIC_DIRNAME,NWM_FILE_TO_SUBSET_WITH,overwrite_wbd,num_workers)

    # Create HUC list files.
    build_huc_list_files(path_to_saved_data_parent_dir, wbd_directory)


if __name__ == '__main__':

    # Parse arguments.
    parser = argparse.ArgumentParser(description='Acquires and preprocesses WBD and NHD data for use in fim_run.sh.')
    parser.add_argument('-u','--hucs-of-interest',help='HUC4, series of HUC4s, or path to a line-delimited file of HUC4s to acquire.',required=True,nargs='+')
    #parser.add_argument('-j','--num-workers',help='Number of workers to process with',required=False,default=1,type=int)
    parser.add_argument('-nd', '--overwrite-nhd-dem', help='Optional flag to overwrite NHDPlus DEM Data',required=False,action='store_true',default=False)
    parser.add_argument('-ng', '--overwrite-nhd-gdb', help='Optional flag to overwrite NHDPlus GDB Data',required=False,action='store_true',default=False)
    parser.add_argument('-w', '--overwrite-wbd', help='Optional flag to overwrite WBD Data',required=False,action='store_true')

    # Extract to dictionary and assign to variables.
    args = vars(parser.parse_args())

    manage_preprocessing(**args)
