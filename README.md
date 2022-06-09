# Human Detection and Count | on Jetson Nano

This README will be a guide for users to setup the Jetson Nano to work with the Human Detection and Count, which uses a
YOLOv5 model and PyTorch.

This project runs in the background as a systemd service and awaits a command from IoT Central to capture an image using
the Ricoh Theta Z1 camera at specified places, run inferencing on the image, extract the number of persons and empty
seats as well as other data, send this data as telemetries to IoT Central, runs face blurring on the inferenced image,
uploads the face-blurred inferenced image to Azure Web Storage, and then awaits for another IoT Central command.

---

## Prerequisites

- ### Python 3.8

**Python3.8** is needed since YOLOv5 requires Python>=3.8 to work.

- ### YOLOv5

**YOLOv5** is a family of compound-scaled object detection models trained on the COCO dataset, and is used to run
inference on images to detect and count objects; this data will be sent as telemetries to IoT Central where the user can
view and qeury them.

- ### libgphoto2 & python-gphoto2

**libgphoto2** is a library that can be used by applications to access various digital cameras and is used as a means
for the device to communicate with the camera.
**python-gphoto2** is a comprehensive Python interface (or binding) to libgphoto2 and this gives direct access to nearly
all the libgphoto2 functions.

- ### Blur360

This [GitHub project by Jan Schmidt](https://github.com/thaytan/blur360) aims to provide face blurring and obscuring for
360 images and videos in equirectangular projection. Equirectangular projection presents some special challenges for
face detection and blurring due to the strong distortion away from the equator.

This project detects faces in several re-projections of the input frame, moving an area of interest into the equatorial
zone on each pass, finding faces and then re-projecting the obscured version back to the original frame for output.

## How to Set Up a Jetson Nano

#### Install Python3.8

In a nutshell, what we'll do is install Python 3.8 and change the default `python3` from `python3.6` to `python3.8`

```shell
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
```

ENTER

```shell
sudo apt install python3.8
sudo apt-get install python3.8-dev python3.8-venv
sudo apt install python3.8-distutils
sudo apt install python3-pip

sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.6 1
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.8 2
sudo update-alternatives --config python3
```

Choose Python3.8’s option

```shell
python3 -m pip install --upgrade pip
wget https://bootstrap.pypa.io/get-pip.py
python3 get-pip.py --force-reinstall
rm get-pip.py
```

-----

#### Install libgphoto2

To install libgphoto2, we must download its compressed archive file, extract it, and then start the installation
process. [LINK](https://github.com/gphoto/libgphoto2/blob/master/INSTALL)

To do so, run the following commands:

```shell
wget -c https://sourceforge.net/projects/gphoto/files/latest/download -O libgphoto2.tar.bz2
tar xf libgphoto2.tar.bz2
cd libgphoto2-*
./configure --prefix=/usr/local
make
sudo make install
```

After installing libgphoto2, we should stop 1 *or* 2 processes from running, since they interfere with our ability to
capture an image using the library. These processes give out the error: **Could not claim the USB device**.

To permanently stop these processes, run the following commands:

```shell
sudo chmod -x /usr/lib/gvfs/gvfs-gphoto2-volume-monitor
sudo chmod -x /usr/lib/gvfs/gvfsd-gphoto2
```

*The second command may or may not be needed; it differs from system to system*

-----

#### Clone the HumanDetectionAndCount GitHub repository

To clone the GitHub repository that is on GlobalDWS's GitHub projects page, we must first install the `git` command on
the Jetson Nano. After doing so, we must clone the repo to the home directory `~`.

To do so, run the following commands:

```shell
sudo apt install git
cd ~
git clone https://github.com/jamal-zaghmout/HumanDetectionAndCount.git
```

-----

#### Clone the YOLOv5 GitHub repository

We should clone the YOLOv5 repository inside of the `HumanDetectionAndCount` directory. To do so, run the following
commands:

```shell
cd HumanDetectionAndCount
git clone https://github.com/ultralytics/yolov5.git
```

After doing so, we need to dowload the YOLOv5x6 model we're going to use for inferencing.

To do so, run the following command:

```shell
wget https://github.com/ultralytics/yolov5/releases/download/v6.1/yolov5x6.pt
```

-----

#### Create a Python virtual environment and install requirements

We should create a Python venv called `.venv` inside of the `HumanDetectionAndCount` directory and install all
requirements in the `requirements.txt` file. To do so, run the following commands:

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
rm gphoto2-2.3.3-cp38-cp38-linux_aarch64.whl
```

*python-gphoto2 will be installed as well when we install requirements from `requirements.txt` so we'll remove the wheel
file right after installation.*

---

#### Clone the blur360 GitHub repository

We should clone the blur360 repository inside of the `HumanDetectionAndCount` directory. To do so, run the following
commands:

```shell
git clone https://github.com/thaytan/blur360.git
```

Then, we should compile and build the project. To do that, we need `meson` and `OpenCV`. We will get `meson` from
installing the requirements in `requirements.txt`; `OpenCV` should already be included in the Jetson Nano as part of
Jetpack 4.6.1 .

To build the project, run the following commands:

```shell
cd blur360/
meson build
ninja -C build
```

After building, we should be able to use the `equirect-blur-image` command in `build/src/`.

-----

#### Create a Systemd service

A systemd service is needed so that the code runs at startup each time the Jetson Nano reboots. But before creating a
unit file for the service, we should first know the username. To do so, run the following command:

```shell
whoami
```

We are going to alter the contents of the below unit file example and use it instead of `<USER>`; *inequality symbols
should be removed as well*.

To create a unit file for the service, run the following command:

```shell
sudo gedit /etc/systemd/system/RunWIP.service
```

Once the text editor is open, copy the following:

```ini
[Unit]
Description = Run WIP service to activate WIP code to receive IoT Central commands to take pictures and run inference and upload results as telemetries to IoT Central and upload the inferenced image to Azure Web Storage.
After = network-online.target
Wants = network-online.target systemd-networkd-wait-online.service

[Service]
Type = simple

WorkingDirectory = /home/<USER>/HumanDetectionAndCount/
User = <USER>
Environment = "PYTHONPATH=$PYTHONPATH:/home/<USER>/HumanDetectionAndCount/.venv/lib/python3.8/site-packages/"

ExecStartPre = /bin/sleep 150
ExecStart = /bin/bash -c 'cd /home/<USER>/HumanDetectionAndCount/ && source .venv/bin/activate && python3 WIP_Camera.py'

Restart = on-failure
RestartSec = 5s

[Install]
WantedBy = multi-user.target
```

**SAVE** and **EXIT**.

In a nutshell, what this service does is wait for 150 seconds after startup and then runs the `WIP_Camera.py` Python
script, which provisions and assigns the device and waits for a command from IoT Central to run `HumanCount.py`. Then,
the attached camera (*Ricoh Theta Z1*) captures an image and the Jetson Nano runs inference on it, uploads the results
as telemetries to IoT Central, uploads the inferenced image to Azure Web Storage, and then awaits for another IoT
Central command.

To enable the service to run at startup, run the following command:

```shell
sudo systemctl enable RunWIP
```

To start the service now, run the following command:

```shell
sudo systemctl start RunWIP
```

To check the status of the service, run the following command:

```shell
sudo systemctl status RunWIP
```

-----

#### End of README.md
