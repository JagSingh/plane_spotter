# syntax=docker/dockerfile:1
# (c) jag.m.singh@gmail.com

# floating tag chosen so Debian security updates land on rebuild; 
# pin by digest only if a base change ever breaks something
FROM python:3.14-slim-bookworm

# tzdata so datetime.fromtimestamp() renders CST, not UTC (TZ set in compose).
# libglib2.0-0 is the one runtime lib opencv-python-headless needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# requirements.txt carries the CPU-only torch index and pins, so the image
# and a bare-metal venv install exactly the same set.
RUN pip install --no-cache-dir -r requirements.txt \
    # ultralytics drags in the GUI build of opencv; replace it with the
    # headless build so the image doesn't need X11/libGL.
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless==4.11.0.86 \
    # Report any CUDA wheels that slipped in. --extra-index-url lets pip
    # still see PyPI, so it can resolve a CUDA candidate mid-resolution.
    # Reported, not fatal — check the build log and the final image size.
    && (pip list 2>/dev/null | grep -i "^nvidia-\|^cuda" \
        && echo "WARNING: CUDA packages present, image will be large" \
        || echo "OK: no CUDA packages")

# Bake the YOLO weights into the image so the container never downloads
# them at runtime (and works without egress).
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY get_config.py gcs.py capture_picture.py capture_radio_data.py create_document.py ./

# Non-root; the 'video' group grants /dev/video* access on Debian/Ubuntu hosts.
# UID/GID must match the host owner of /var/lib/plane-spotter, or the
# container can't write the daily HTML files to the bind mount.
# Check with: id -u ; id -g   and override via build args if not 1000.
ARG UID=1000
ARG GID=1000
# No home directory needed — all paths are absolute, so nothing resolves
# against ~ and the username is irrelevant to the mounts.
RUN groupadd -g ${GID} spotter 2>/dev/null || true \
    && useradd --no-create-home --shell /usr/sbin/nologin -u ${UID} -g ${GID} spotter \
    && usermod -aG video spotter \
    && chown -R spotter:spotter /app
USER spotter

# ultralytics writes a settings file and matplotlib a font cache on import.
# The spotter user has no home directory, so point both at /tmp or they
# fail/warn at runtime.
ENV PLANE_SPOTTER_CONFIG=/etc/plane-spotter/config.yaml \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

CMD ["python", "capture_radio_data.py"]
