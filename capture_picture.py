import cv2
from ultralytics import YOLO
import time
import get_config
import os
from google.cloud import storage
from datetime import datetime
import create_document

# Load the YOLO model
model = YOLO('yolov8n.pt') 

def detect_and_upload_airplane(cst_time, aircraft_data={}, video_source='/dev/video2', monitor_duration=30):
    # Open video capture from the specified source, minitor duration provided in seocnds
    video_capture = cv2.VideoCapture(video_source)
    video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    if not video_capture.isOpened():
        print("Error: Could not open video source.")
        return

    start_time = time.time()

    # Initialize the state variables
    no_plane_path = os.path.join(get_config.log_dir, 'no_plane.png')  # No longer useful, can be set to None
    biggest_plane = cv2.imread(no_plane_path)
    prev_box_area = 0
    plane_detected = False

    while True:
        ret, frame = video_capture.read()
        if not ret:
            print("Error: Could not read frame.")
            break

        # Perform object detection
        # Stop this output with verbose=False:
        # 0: 384x640 (no detections), 48.4ms
        # Speed: 1.7ms preprocess, 48.4ms inference, 0.6ms postprocess per image at shape (1, 3, 384, 640)
        results = model(frame, verbose=False)

        # Crop the image to the bounding box of the first detection (if any)
        if results[0].boxes:
            box = results[0].boxes[0]  # Get the first detected box

            class_id = int(box.cls)  # Convert class index to integer
            class_name = model.names[class_id]  # Lookup class name using the model's class names
            x1, y1, x2, y2 = map(int, box.xyxy[0])  # Extract coordinates
            cropped_frame = frame[y1:y2, x1:x2]
            box_area = (x2 - x1) * (y2 - y1)  # Calculate the area of the bounding box
            if box_area > prev_box_area and class_name == "airplane":
                biggest_plane = cropped_frame
                prev_box_area = box_area
                plane_detected = True

        # Display the cropped frame
        if plane_detected:
            cv2.imshow('Airplane Detection', biggest_plane)
        else:
            cv2.imshow('Airplane Detection', frame)

        # Monitor visible space for the specified duration and stop
        if time.time() - start_time > monitor_duration:
            print(f"{monitor_duration} seconds elapsed. Exiting...")
            break

        # Exit on pressing 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Save the biggest detected airplane image
    if plane_detected:
        formatted_time = time.strftime('%Y%m%d%H%M%S', time.localtime(cst_time.timestamp()))
        success, buffer = cv2.imencode('.jpg', biggest_plane, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if success:
            image_data = buffer.tobytes()
            bucket = storage.Client.from_service_account_json(get_config.credentials_file).bucket(get_config.bucket_name)
            blob = bucket.blob(f'{formatted_time}.jpg')
            blob.upload_from_string(image_data, content_type='image/jpeg')

            create_document.update_html_file(cst_time, aircraft_data, f'{formatted_time}.jpg')

        else:
            print("Error: Could not encode image to JPEG format for GCS upload.")
    else:
        print("No airplane detected in the visible space.")

    # Release resources
    video_capture.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    detect_and_upload_airplane(datetime.now())


"""
Setup software

$ lsusb
Bus 001 Device 009: ID 32e4:9230 HD USB Camera HD USB Camera

$ pip3 install ultralytics

$ pip3 install google-cloud-storage

"""
