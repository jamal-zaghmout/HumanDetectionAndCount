import asyncio
import csv
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from time import sleep

import pandas as pd
import requests
from azure.iot.device import Message
from azure.iot.device.aio import IoTHubDeviceClient
from azure.iot.device.aio import ProvisioningDeviceClient
from azure.storage.blob import BlobServiceClient
from exif import Image
from requests.auth import HTTPDigestAuth

os.chdir(os.path.dirname(os.path.realpath(__file__)))


def captureImageAndGetResponse(THETA_URL, THETA_ID, THETA_PASSWORD):
    # From takePicture() func in 'codetricity/theta-client-mode/simple-client.py' | WITH FEW ALTERATIONS
    url = THETA_URL + 'commands/execute'
    payload = {"name": "camera.takePicture"}
    req1 = requests.post(url,
                         json=payload,
                         auth=(HTTPDigestAuth(THETA_ID, THETA_PASSWORD)))

    resp1 = req1.json()
    print("TakePicture EXECUTED")
    print(resp1)

    # Wait 8 seconds to make sure the image was saved on the device
    print('Wait 8 seconds')
    sleep(8)

    # From listFiles() func in 'codetricity/theta-client-mode/simple-client.py' | WITH ALTERATIONS
    url = THETA_URL + 'commands/execute'
    commandString = "camera.listFiles"
    payload = {
        "name": commandString,
        "parameters": {
            "fileType": "image",
            "entryCount": 1,
            "maxThumbSize": 0
        }}
    req2 = requests.post(url,
                         json=payload,
                         auth=(HTTPDigestAuth(THETA_ID, THETA_PASSWORD)))

    resp2 = json.dumps(req2.json())
    responseJsonData = json.loads(resp2)

    return responseJsonData


def getImageByUrl(image_url, THETA_ID, THETA_PASSWORD):
    print('Downloading image locally')
    image_name = image_url.split("/")[-1]

    print("Saving " + image_name + " to file")
    with open(image_name, 'wb') as handle:
        response = requests.get(
            image_url,
            stream=True,
            auth=(HTTPDigestAuth(THETA_ID, THETA_PASSWORD)))

        if not response.ok:
            print(response)
        for block in response.iter_content(1024):
            if not block:
                break
            handle.write(block)


def photoInferenceAndGetInferenceResults(image_name):
    """
    Function to call a subprocess to run the yolov5/detect.py file to run inference on the image taken by the Ricoh cam.
    :param image_name: Name of last image taken by the Ricoh Theta Z1 camera; retrieved by the Ricoh API.
    :return: Returns List containing number of persons AND number of chairs detected.
    """

    try:
        # Run inference using YOLOv5's 'detect.py' to customize output
        subprocess.call(
            ['python3', os.path.join(os.path.dirname(__file__), '../yolov5/detect.py'), '--weights', 'yolov5x6.pt',
             '--source', image_name, '--classes', '0', '56', '--conf-thres', '0.7', '--hide-conf',
             '--line-thickness', '15', '--project', os.path.join(os.path.dirname(__file__), '../runs/detect'),
             '--exist-ok', '--save-txt']
        )
    except:
        logging.exception('Could not run inference on image; Inferencing Failed')

    RDEdirectory = os.path.join(os.path.dirname(__file__), '../runs/detect/exp/')
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

def stdin_listener():
    """
    Listener for quitting the sample
    """
    while True:
        selection = input("Press Q to quit\n")
        if selection == "Q" or selection == "q":
            print("Quitting...")
            break


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


def extractMetadata(image_name):
    try:
        with open(image_name, 'rb') as image_file:
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
    datetime_obj = datetime.strptime(datetime_metadata, '%Y:%m:%d %H:%M:%S%z').isoformat()

    metadata = [datetime_obj, gps_latitude, gps_longitude, gps_altitude]

    return metadata


async def uploadBlobToAzureAndRemoveRunsDirectoryAndLocalImage(conn_str, altered_filename, image_name, runs_dir):
    # Create the BlobServiceClient object
    blob_service_client = BlobServiceClient.from_connection_string(conn_str)
    container_name = 'wipcontainer'

    upload_file_path = 'runs/detect/exp/' + altered_filename

    # Create a blob client using the local file name as the name for the blob
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=altered_filename)

    # Upload the created file
    print("\nUploading to Azure Storage as blob:\n\t" + altered_filename)
    with open(upload_file_path, "rb") as data:
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
    env_var_path = os.path.join(os.path.dirname(__file__), '../DeviceEnvironment_Camera.csv')
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
    THETA_ID = Device['THETA_ID']
    THETA_PASSWORD = Device['THETA_PASSWORD']
    THETA_URL = Device['THETA_URL']

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

    # Capture the image on the camera and receive a JSON response to get info from for renaming
    responseJsonData = captureImageAndGetResponse(THETA_URL, THETA_ID, THETA_PASSWORD)

    # ––––– Retrieve metadata from the received JsonData response ––––– #
    image_name = responseJsonData['results']['entries'][0]['name']
    last_photo_url = responseJsonData['results']['entries'][0]['fileUrl']
    timestamp = responseJsonData['results']['entries'][0]['dateTimeZone']

    # Example dateTimeZone as sent from the API = '2022:05:13 18:20:14-04:00'
    timestamp = timestamp.replace(':', '')
    timestamp = timestamp.replace(' ', '_')

    # Save image taken by the camera on the Jetson Nano (locally)
    getImageByUrl(last_photo_url, THETA_ID, THETA_PASSWORD)

    # Run inference on it then save results and return # of persons and extract metadata
    inference_results = photoInferenceAndGetInferenceResults(image_name)
    number_of_persons = int(inference_results[0])
    number_of_chairs = int(inference_results[1])
    metadata = extractMetadata(image_name)
    datetime_str = str(metadata[0])
    gps_latitude = float(metadata[1])
    gps_longitude = float(metadata[2])
    gps_altitude = int(metadata[3])

    location_id_str = str(location_id)

    # Rename inferenced file
    altered_filename = location_id_str + '_' + timestamp + '.JPG'  # Example output: 'Room07_20220513_182014-0400.JPG'

    RDEdir = os.path.join(os.path.dirname(__file__), '../runs/detect/exp/')
    os.rename(RDEdir + image_name, RDEdir + altered_filename)

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

    # Move inferenced image to Azure Web Storage
    await uploadBlobToAzureAndRemoveRunsDirectoryAndLocalImage(conn_str, altered_filename, image_name, '../runs/')
