# Camera setup: HD USB camera on the north laptop

`capture_picture.py` reads frames from a single UVC camera through OpenCV
(`cv2.VideoCapture(video_source)`) at 1920×1080. This document covers how to
connect that camera, find a stable device path for it, and set `video_source`
for bare-metal and Docker runs.

| | |
|---|---|
| Camera | HD USB Camera, USB ID `32e4:9230` |
| Host | North laptop (see [receiver-setup.md](receiver-setup.md)) |
| Config key | `video_source` (default `/dev/video0`, see `get_config.py`) |

Contents

1. [Software](#1-software)
2. [Connect the camera](#2-connect-the-camera)
3. [Find the stable device path](#3-find-the-stable-device-path)
4. [Confirm it is the right camera](#4-confirm-it-is-the-right-camera)
5. [Set `video_source`](#5-set-video_source)

---

## 1. Software

The Docker image installs the Python dependencies itself. For a bare-metal run:

```bash
pip3 install -r requirements.txt
```

The checks below also use `v4l2-ctl` and `ffplay`:

```bash
sudo apt install v4l-utils ffmpeg    # v4l2-ctl, ffplay
```

## 2. Connect the camera

Plug the camera into a laptop root port, not into the USB-C dock. The rule is
the same as for the ADS-B stick ([receiver-setup.md §1](receiver-setup.md#1-north-laptop-receiver-hardware)):
check the **port path**, not the bus number. A path with no dot has no hub in
between.

```bash
for d in /sys/bus/usb/devices/*; do
  [ "$(cat $d/idProduct 2>/dev/null)" = 9230 ] && echo "${d##*/}  $(cat $d/speed) Mb/s"
done
# 3-4    good: root port
# 3-2.1  bad:  behind the dock hub
```

Confirm the camera enumerates:

```bash
lsusb
# Bus 001 Device 009: ID 32e4:9230 HD USB Camera HD USB Camera
```

## 3. Find the stable device path

Pin the camera by its `/dev/v4l/by-id/` path, not by `/dev/videoN`. The `N` is
allocation order and carries no meaning; it shifts across reboots and replugs
when more than one video device is attached.

```bash
ls -l /dev/v4l/by-id/
# usb-HD_USB_Camera_HD_USB_Camera-video-index0 -> ../../video2
# usb-HD_USB_Camera_HD_USB_Camera-video-index1 -> ../../video3
```

Each UVC camera exposes two nodes:

| Node | Content | Usable by OpenCV |
|---|---|---|
| `-video-index0` | Capture stream | Yes |
| `-video-index1` | UVC metadata (timestamps, frame counters) | No |

Use the `-video-index0` entry. Match on the by-id name, never on the video
number it points to.

## 4. Confirm it is the right camera

```bash
CAM=/dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0
v4l2-ctl --device="$CAM" --info    # should report HD USB Camera
ffplay "$CAM"                       # live window
```

The `ffplay` window should show the sky. Aim the camera before the first
capture run.

## 5. Set `video_source`

The value depends on where `capture_picture.py` runs. Both cases end up on the
same physical camera.

**Bare metal.** Use the by-id path directly:

```yaml
video_source: /dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0
```

**Docker.** `docker-compose.yml` maps the by-id path to a fixed name inside
the container, so the by-id path lives only in the compose file:

```yaml
# docker-compose.yml
devices:
  - /dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0:/dev/video0
```

```yaml
# /etc/plane-spotter/config.yaml
video_source: /dev/video0
```

The container user needs the host's `video` group (GID 44 on Debian and
Ubuntu). The compose file adds it with `group_add`. Check the host value with
`getent group video`.

`docker-compose.yml` also documents an alternative: a udev rule that creates
`/dev/plane-camera` from `idVendor` `32e4` / `idProduct` `9230`, mapped the
same way.
