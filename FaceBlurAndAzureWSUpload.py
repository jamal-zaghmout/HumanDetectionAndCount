import logging
import os
import shutil
import subprocess
from multiprocessing import Pool

from azure.storage.blob import BlobServiceClient


def faceBlur(image_name, altered_filename):
    print('=' * 60)

    inferenced_image_filepath = os.path.join(os.path.dirname(__file__), 'runs/detect/exp/' + image_name)
    inferenced_blurred_output_filepath = os.path.join(os.path.dirname(__file__), 'runs/detect/exp/' + altered_filename)

    try:
        # Blur faces on inferenced image using Jan Schmidt's 'blur360' project
        # cmd: blur360/build/src/equirect-blur-image -b -m=blur360/models -o=output_name.jpg inferenced_image_name.JPG
        subprocess.call(
            [
                'blur360/build/src/equirect-blur-image',
                '-b',
                '-m=blur360/models',
                '-o=' + inferenced_blurred_output_filepath,
                inferenced_image_filepath
            ]
        )
    except:
        logging.exception('Could not run face blurring inferenced image!')


def uploadBlobToAzure(conn_str, altered_filename):
    print('=' * 60)

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


def removeRunsDirectoryAndLocalImage(image_name, runs_dir):
    print('=' * 60)

    # Delete the local directory the inferenced file is stored in after uploading it as a blob to Azure Blob Storage
    try:
        os.remove(image_name)
        shutil.rmtree(runs_dir)
        print('Deleted relevant file and dir')
    except:
        logging.exception("Couldn't remove either the image OR the runs directory OR both.")


def main(conn_str, image_name, altered_filename, runs_dir):
    logging.info('FACE BLURRING STARTED')
    faceBlur(image_name, altered_filename)
    logging.info('FACE BLURRING COMPLETE')

    logging.info('UPLOADING TO AZURE WEB STORAGE STARTED')
    uploadBlobToAzure(conn_str, altered_filename)
    logging.info('UPLOADING TO AZURE WEB STORAGE COMPLETE')

    removeRunsDirectoryAndLocalImage(image_name, runs_dir)
    logging.info('REMOVING RUNS DIRECTORY AND LOCAL IMAGE COMPLETE')
