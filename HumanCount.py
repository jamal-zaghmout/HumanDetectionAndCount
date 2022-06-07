import asyncio
import csv
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
from azure.iot.device import Message
from azure.iot.device.aio import IoTHubDeviceClient
from azure.iot.device.aio import ProvisioningDeviceClient
from azure.storage.blob import BlobServiceClient
from exif import Image

import gphoto2 as gp

os.chdir(os.path.dirname(os.path.realpath(__file__)))


def captureImageAndExtractMetadata():
    # Capturing the image via USB
    camera = gp.Camera()
    camera.init()
    print('Capturing image')
    file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
    print('Camera file path: {0}/{1}'.format(file_path.folder, file_path.name))
    target = os.path.join(os.path.dirname(__file__), file_path.name)
    print('Copying image to', target)
    camera_file = camera.file_get(
        file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)
    camera_file.save(target)
    camera.exit()

    # Extracting metadata
    try:
        with open(file_path.name, 'rb') as image_file:
            image = Image(image_file)

        gps_latitude = dms_coordinates_to_dd_coordinates(image.gps_latitude, image.gps_latitude_ref)
        gps_longitude = dms_coordinates_to_dd_coordinates(image.gps_longitude, image.gps_longitude_ref)
        gps_altitude = image.gps_altitude
    except:
        logging.exception('GPS information could not be retrieved')
        gps_latitude = 0
        gps_longitude = 0
        gps_altitude = 0

    datetime_metadata = image.datetime_original + image.offset_time

    metadata = [str(file_path.name), datetime_metadata, gps_latitude, gps_longitude, gps_altitude]

    return metadata


def photoInferenceAndGetInferenceResults(image_name):
    """
    Function to call a subprocess to run the yolov5/detect.py file to run inference on the image taken by the Ricoh cam.
    :param image_name: Name of last image taken by the Ricoh Theta Z1 camera; retrieved by the Ricoh API.
    :return: Returns List containing number of persons AND number of chairs detected.
    """

    try:
        # Run inference using YOLOv5's 'detect.py' to customize output
        subprocess.call(
            [
                'python3', os.path.join(os.path.dirname(__file__), 'yolov5/detect.py'),
                '--weights', 'yolov5x6.pt',
                '--source', image_name,
                '--classes', '0', '56',
                '--conf-thres', '0.7',
                '--hide-conf',
                '--line-thickness', '15',
                '--exist-ok',
                '--save-txt'
                '--project', os.path.join(os.path.dirname(__file__), 'runs/detect'),
            ]
        )
    except:
        logging.exception('Could not run inference on image. Inference Failed!')

    RDEdirectory = os.path.join(os.path.dirname(__file__), 'runs/detect/exp/')
    pre, ext = os.path.splitext(RDEdirectory + image_name)
    labels_filename = pre.split(sep='/')[-1] + '.txt'
    labels_filepath = Path(RDEdirectory + 'labels/' + labels_filename)

    # Check if the labels file exists; if it doesn't, then there were no objects detected in the image
    if labels_filepath.is_file():
        read_detections_file = pd.read_csv(labels_filepath, delim_whitespace=True, header=None)
        read_detections_file.columns = ['Class', '1', '2', '3', '4']
        number_of_persons = len(read_detections_file[read_detections_file['Class'] == int(0)])
        number_of_chairs = len(read_detections_file[read_detections_file['Class'] == int(56)])

    else:
        print('No objects were detected in', image_name)
        number_of_persons = 0
        number_of_chairs = 0

    inference_results = [number_of_persons, number_of_chairs]

    return inference_results


#####################################################
# Azure async Functions

async def provision_device(provisioning_host, id_scope, registration_id, symmetric_key, model_id):
    provisioning_device_client = ProvisioningDeviceClient.create_from_symmetric_key(
        provisioning_host=provisioning_host,
        registration_id=registration_id,
        id_scope=id_scope,
        symmetric_key=symmetric_key,
    )
    provisioning_device_client.provisioning_payload = {"modelId": model_id}
    return await provisioning_device_client.register()


async def send_telemetry_from_nano(device_client, telemetry_msg):
    msg = Message(json.dumps(telemetry_msg))
    msg.content_encoding = "utf-8"
    msg.content_type = "application/json"
    print("Sent message")
    await device_client.send_message(msg)


# END TELEMETRY Functions
#####################################################


def format_dms_coordinates(coordinates):
    try:
        return f"{coordinates[0]}° {coordinates[1]}\' {coordinates[2]}\""
    except:
        logging.exception('GPS information could not be retrieved')
        return 0


def dms_coordinates_to_dd_coordinates(coordinates, coordinates_ref):
    try:
        decimal_degrees = coordinates[0] + \
                          coordinates[1] / 60 + \
                          coordinates[2] / 3600

        if coordinates_ref == "S" or coordinates_ref == "W":
            decimal_degrees = -decimal_degrees

        return decimal_degrees
    except:
        logging.exception('GPS information could not be retrieved')
        return 0


def faceBlur(image_name, altered_filename):
    inferenced_image_filepath = 'runs/detect/exp/' + image_name
    inferenced_blurred_output_filepath = 'runs/detect/exp/' + altered_filename

    try:
        # Blur faces on inferenced image using Jan Schmidt's 'blur360' project
        # command = blur360/build/src/equirect-blur-image -m=models -o=output_name.jpg inferenced_image_name.JPG
        subprocess.call(
            [
                'blur360/build/src/equirect-blur-image',
                '-m=models',
                '-o=' + inferenced_blurred_output_filepath,
                inferenced_image_filepath
            ]
        )
    except:
        logging.exception('Could not run face blurring inferenced image!')


async def uploadBlobToAzureAndRemoveRunsDirectoryAndLocalImage(conn_str, altered_filename, image_name, runs_dir):
    # Create the BlobServiceClient object
    blob_service_client = BlobServiceClient.from_connection_string(conn_str)
    container_name = 'wipcontainer'

    inferenced_blurred_output_filepath = 'runs/detect/exp/' + altered_filename

    # Create a blob client using the local file name as the name for the blob
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=altered_filename)

    # Upload the created file
    print("\nUploading to Azure Storage as blob:\n\t" + altered_filename)
    with open(inferenced_blurred_output_filepath, "rb") as data:
        blob_client.upload_blob(data)

    # Delete the local directory the inferenced file is stored in after uploading it as a blob to Azure Blob Storage
    try:
        os.remove(image_name)
        shutil.rmtree(runs_dir)
        print('Deleted relevant file and dir')
    except:
        logging.exception("Couldn't remove either the image OR the runs directory OR both.")


async def main(location_id):
    # ––––– Define IOT central Variables saved in the CSV file ––––– #
    env_var_path = os.path.join(os.path.dirname(__file__), 'DeviceEnvironment_Camera.csv')
    with open(env_var_path, newline='') as fp:
        csvreader = csv.DictReader(fp)
        for row in csvreader:
            Device = row

    IOTHUB_DEVICE_SECURITY_TYPE = Device['IOTHUB_DEVICE_SECURITY_TYPE']
    IOTHUB_DEVICE_DPS_ID_SCOPE = Device['IOTHUB_DEVICE_DPS_ID_SCOPE']
    IOTHUB_DEVICE_DPS_DEVICE_KEY = Device['IOTHUB_DEVICE_DPS_DEVICE_KEY']
    IOTHUB_DEVICE_DPS_DEVICE_ID = Device['IOTHUB_DEVICE_DPS_DEVICE_ID']
    IOTHUB_DEVICE_DPS_ENDPOINT = Device['IOTHUB_DEVICE_DPS_ENDPOINT']

    conn_str = Device['AZURE_WEB_STORAGE_CONNECTION_STRING']
    model_id = Device['model_id']

    # ––––– Connecting to IoT Central ––––– #
    switch = IOTHUB_DEVICE_SECURITY_TYPE
    if switch == "DPS":
        provisioning_host = (
            IOTHUB_DEVICE_DPS_ENDPOINT
            if IOTHUB_DEVICE_DPS_ENDPOINT
            else "global.azure-devices-provisioning.net"
        )
        id_scope = IOTHUB_DEVICE_DPS_ID_SCOPE
        registration_id = IOTHUB_DEVICE_DPS_DEVICE_ID
        symmetric_key = IOTHUB_DEVICE_DPS_DEVICE_KEY

        registration_result = await provision_device(
            provisioning_host, id_scope, registration_id, symmetric_key, model_id
        )

        if registration_result.status == "assigned":
            print("Device was assigned")
            print(registration_result.registration_state.assigned_hub)
            print(registration_result.registration_state.device_id)

            device_client = IoTHubDeviceClient.create_from_symmetric_key(
                symmetric_key=symmetric_key,
                hostname=registration_result.registration_state.assigned_hub,
                device_id=registration_result.registration_state.device_id,
                product_info=model_id,
            )
        else:
            raise RuntimeError(
                "Could not provision device. Aborting Plug and Play device connection."
            )

    elif switch == "connectionString":
        conn_str = os.getenv("IOTHUB_DEVICE_CONNECTION_STRING")
        print("Connecting using Connection String " + conn_str)
        device_client = IoTHubDeviceClient.create_from_connection_string(
            conn_str, product_info=model_id
        )
    else:
        raise RuntimeError(
            "At least one choice needs to be made for complete functioning of this sample."
        )

    await device_client.connect()
    # ––––– End of Connecting to IoT Central ––––– #

    # Capture the image on the camera and extract metadata from picture taken
    metadata = captureImageAndExtractMetadata()

    # ––––– Retrieve metadata from the received response ––––– #
    # [str(file_path.name), datetime_obj, gps_latitude, gps_longitude, gps_altitude]
    image_name = metadata[0]
    datetime_str = metadata[1]
    gps_latitude = float(metadata[2])
    gps_longitude = float(metadata[3])
    gps_altitude = int(metadata[4])

    # Example dateTimeZone as sent from the API = '2022:05:13 18:20:14-04:00'; Convert to '20220513_182014-0400'
    timestamp = datetime_str.replace(':', '')
    timestamp = timestamp.replace(' ', '_')

    # Run inference on it then save results and return # of persons and extract metadata
    inference_results = photoInferenceAndGetInferenceResults(image_name)
    number_of_persons = int(inference_results[0])
    number_of_chairs = int(inference_results[1])

    # Choose face-blurred inferenced filename
    altered_filename = str(location_id) + '_' + timestamp + '.JPG'  # Example output: '07_20220513_182014-0400.JPG'

    # Send the data as telemetries to Azure IoT Central | WIP
    async def send_telemetry():

        WIP_Robot_Camera_msg = {"FileName": altered_filename, "LocationID": float(location_id),
                                "NumberOfPersons": number_of_persons, "NumberOfEmptySeats": number_of_chairs,
                                "DateTime": datetime_str, "GPS_Latitude": gps_latitude, "GPS_Longitude": gps_longitude,
                                "GPS_Altitude": gps_altitude}
        await send_telemetry_from_nano(device_client, WIP_Robot_Camera_msg)
        await asyncio.sleep(8)

    await send_telemetry()
    await device_client.shutdown()

    # Blur faces in inferenced image
    faceBlur(image_name, altered_filename)

    # Move inferenced image to Azure Web Storage
    await uploadBlobToAzureAndRemoveRunsDirectoryAndLocalImage(conn_str, altered_filename, image_name, 'runs/')
