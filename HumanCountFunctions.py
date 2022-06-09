import json
import logging
import os
import subprocess
from pathlib import Path

import gphoto2 as gp
import pandas as pd
from azure.iot.device import Message
from azure.iot.device.aio import ProvisioningDeviceClient
from exif import Image


def captureImageAndExtractMetadata():
    print('=' * 60)

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
    with open(file_path.name, 'rb') as image_file:
        image = Image(image_file)

    try:
        gps_latitude = dms_coordinates_to_dd_coordinates(image.gps_latitude, image.gps_latitude_ref)
        gps_longitude = dms_coordinates_to_dd_coordinates(image.gps_longitude, image.gps_longitude_ref)
        gps_altitude = image.gps_altitude
    except AttributeError:
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

    print('=' * 60)

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
                '--save-txt',
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
