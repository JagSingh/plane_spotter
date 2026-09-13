# (c) jag.m.singh@gmail.com
import logging
import time

import cv2

import create_document
import gcs
import get_config

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    """Load the YOLO model weights once, only on first use"""
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO("yolov8n.pt")
    return _model


def detect_and_upload_airplane(cst_time, aircraft_data=None,
                               video_source=None, monitor_duration=None):
    """Watch the camera for `monitor_duration` seconds, keep the largest
    airplane crop seen, upload it to GCS, and append it to the daily HTML."""
    aircraft_data = aircraft_data or {}
    video_source = video_source if video_source is not None else get_config.video_source
    monitor_duration = monitor_duration if monitor_duration is not None else get_config.monitor_duration
    show_preview = get_config.show_preview

    model = _get_model()

    video_capture = cv2.VideoCapture(video_source)
    video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    if not video_capture.isOpened():
        logger.error("Could not open video source %s", video_source)
        return

    start_time = time.time()
    biggest_plane = None
    prev_box_area = 0

    try:
        while True:
            ret, frame = video_capture.read()
            if not ret:
                logger.error("Could not read frame.")
                break

            # verbose=False suppresses per-frame inference logging
            results = model(frame, verbose=False)

            # Check ALL detections in the frame, not just the first box.
            # the first box mught be another object (bird,
            # kite, etc.) happened to be detected first.
            for box in results[0].boxes:
                class_name = model.names[int(box.cls)]
                if class_name != "airplane":
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0])  # Extract coordinates
                box_area = (x2 - x1) * (y2 - y1)  # Calculate the area of the bounding box
                if box_area > prev_box_area:
                    biggest_plane = frame[y1:y2, x1:x2] # Cropped box
                    prev_box_area = box_area

            # Optional live preview — must stay off in Docker/headless mode.
            if show_preview:
                try:
                    cv2.imshow("Airplane Detection",
                               biggest_plane if biggest_plane is not None else frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except cv2.error:
                    logger.warning("No display available; disabling preview.")
                    show_preview = False

            if time.time() - start_time > monitor_duration:
                logger.info("%s seconds elapsed. Exiting capture loop.", monitor_duration)
                break
    finally:
        video_capture.release()
        if show_preview:
            cv2.destroyAllWindows()

    if biggest_plane is None:
        logger.info("No airplane detected in the visible space.")
        return

    formatted_time = time.strftime("%Y%m%d%H%M%S", time.localtime(cst_time.timestamp()))
    success, buffer = cv2.imencode(".jpg", biggest_plane, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        logger.error("Could not encode image to JPEG format for GCS upload.")
        return

    blob = gcs.bucket().blob(f"{formatted_time}.jpg")
    blob.upload_from_string(buffer.tobytes(), content_type="image/jpeg")
    create_document.update_html_file(cst_time, aircraft_data, f"{formatted_time}.jpg")


"""
Setup software (bare metal; the Docker image installs these itself)

$ pip3 install -r requirements.txt

Check that camera shows up
lsusb
Bus 001 Device 009: ID 32e4:9230 HD USB Camera HD USB Camera

Test camera
ffplay /dev/videoN

Identify and pin the camera by its /dev/v4l/by-id/ path rather than
/dev/videoN, which shifts across reboots when several cameras are attached.
Each UVC camera exposes two nodes: the -video-index0 entry is the capture
stream, -video-index1 is UVC metadata (timestamps, frame counters) which
OpenCV cannot open. Match on the by-id name, not the video number — the
numbering is allocation order and carries no meaning.

$ sudo apt install v4l-utils # ??
$ ls -l /dev/v4l/by-id/
usb-HD_USB_Camera_HD_USB_Camera-video-index0 -> ../../video2

Confirm it's the right camera

v4l2-ctl --device=/dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0 --info
ffplay /dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0
The --info should report the HD USB Camera, ffplay gives you a live window — confirm it's pointed at the sky.

Update the config

yaml
video_source: /dev/v4l/by-id/usb-HD_USB_Camera_HD_USB_Camera-video-index0

Docker note: the compose file maps by-id path to /dev/video0 inside the container, 
so at docker run time the config value changes to /dev/video0 and the by-id path lives only in docker-compose.yml. 
Bare metal uses the by-id path directly; containerized uses the mapping. Both end up on the same physical camera.

"""
