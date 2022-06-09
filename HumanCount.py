import asyncio
import csv
import os
from multiprocessing import Process

from azure.iot.device.aio import IoTHubDeviceClient

import FaceBlurAndAzureWSUpload
import HumanCountFunctions

os.chdir(os.path.dirname(os.path.realpath(__file__)))


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

        registration_result = await HumanCountFunctions.provision_device(
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
    metadata = HumanCountFunctions.captureImageAndExtractMetadata()

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
    inference_results = HumanCountFunctions.photoInferenceAndGetInferenceResults(image_name)
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
        await HumanCountFunctions.send_telemetry_from_nano(device_client, WIP_Robot_Camera_msg)
        await asyncio.sleep(8)

    await send_telemetry()
    await device_client.shutdown()
    print('Telemetries have been sent to IoT Central')

    # Fire and Forget | Using the multiprocessing module | To run the 'FaceBlurAndAzureWSUpload' and return to WIP
    p = Process(target=FaceBlurAndAzureWSUpload.main, args=(conn_str, image_name, altered_filename, 'runs/'))
    p.daemon = True
    p.start()
    print('FaceBlurAndAzureWSUpload started')

    print('=' * 30)
    return
