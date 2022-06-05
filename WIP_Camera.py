import HumanCount
import csv
import os
from time import sleep
import asyncio
from azure.iot.device.aio import IoTHubDeviceClient
from azure.iot.device.aio import ProvisioningDeviceClient
from azure.iot.device import MethodResponse

os.chdir(os.path.dirname(os.path.realpath(__file__)))

# ––––– Define IOT central Variables saved in the CSV file ––––– #
env_var_path = os.path.join(os.path.dirname(__file__), 'DeviceEnvironment_Camera.csv')
with open(env_var_path, newline='') as fp:
    csvreader = csv.DictReader(fp)
    for row in csvreader:
        Device = row

model_id_Command = Device['model_id_Command']
IOTHUB_DEVICE_SECURITY_TYPE_Command = Device['IOTHUB_DEVICE_SECURITY_TYPE_Command']
IOTHUB_DEVICE_DPS_ID_SCOPE_Command = Device['IOTHUB_DEVICE_DPS_ID_SCOPE_Command']
IOTHUB_DEVICE_DPS_DEVICE_KEY_Command = Device['IOTHUB_DEVICE_DPS_DEVICE_KEY_Command']
IOTHUB_DEVICE_DPS_ENDPOINT_Command = Device['IOTHUB_DEVICE_DPS_ENDPOINT_Command']
IOTHUB_DEVICE_DPS_DEVICE_ID_Command = Device['IOTHUB_DEVICE_DPS_DEVICE_ID_Command']


#####################################################
# PROVISION DEVICE
async def provision_device(provisioning_host, id_scope, registration_id, symmetric_key, model_id_Command):
    provisioning_device_client = ProvisioningDeviceClient.create_from_symmetric_key(
        provisioning_host=provisioning_host,
        registration_id=registration_id,
        id_scope=id_scope,
        symmetric_key=symmetric_key,
    )
    provisioning_device_client.provisioning_payload = {"modelId": model_id_Command}
    return await provisioning_device_client.register()


#####################################################
# MAIN STARTS

async def main():
    switch = IOTHUB_DEVICE_SECURITY_TYPE_Command
    # print (switch)
    if switch == "DPS":
        provisioning_host = (IOTHUB_DEVICE_DPS_ENDPOINT_Command
                             if IOTHUB_DEVICE_DPS_ENDPOINT_Command
                             else "global.azure-devices-provisioning.net"
                             )
        id_scope = IOTHUB_DEVICE_DPS_ID_SCOPE_Command
        registration_id = IOTHUB_DEVICE_DPS_DEVICE_ID_Command
        symmetric_key = IOTHUB_DEVICE_DPS_DEVICE_KEY_Command

        registration_result = await provision_device(
            provisioning_host, id_scope, registration_id, symmetric_key, model_id_Command
        )

        if registration_result.status == "assigned":
            print("Device was assigned")
            print(registration_result.registration_state.assigned_hub)
            print(registration_result.registration_state.device_id)

            device_client = IoTHubDeviceClient.create_from_symmetric_key(
                symmetric_key=symmetric_key,
                hostname=registration_result.registration_state.assigned_hub,
                device_id=registration_result.registration_state.device_id,
                product_info=model_id_Command,
            )
        else:
            raise RuntimeError(
                "Could not provision device. Aborting Plug and Play device connection."
            )

    else:
        raise RuntimeError(
            "At least one choice needs to be made for complete functioning of this sample."
        )

    # Connect the client.
    await device_client.connect()

    # define behavior for handling methods
    async def RunWIP(device_client):
        while True:
            method_request = await device_client.receive_method_request(
                "RunWIP"
            )  # Wait for method1 calls
            payload = {"result": True, "data": "some data"}  # set response payload
            status = 200  # set return status code
            print("executed RunWip")
            method_response = MethodResponse.create_from_method_request(
                method_request, status, payload
            )
            locationID = method_request.payload
            await HumanCount.main(locationID)
            # await WIP_Device_Send_Telemetry.main()
            print('done wip')
            await device_client.send_method_response(method_response)  # send response

    await RunWIP(device_client)

    # Finally, disconnect
    await device_client.disconnect()


if __name__ == "__main__":
    while True:
        asyncio.run(main())
