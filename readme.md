# PPE Detection System (YOLO26): Helmet & Vest Compliance Monitoring

A real-time safety monitoring system for construction sites, built with Ultralytics YOLO26. It detects workers who are not wearing a helmet or a safety vest, records each violation in a web dashboard, and sends an alert with the photo to Telegram.

**Author:** Đặng Gia Khánh, Information Technology student at the Posts and Telecommunications Institute of Technology (PTIT), Hanoi, Vietnam
**Status:** Version 1.0, academic project (Aug 2026 – present)

---

## Demo

[Watch the system demo on Google Drive](https://drive.google.com/file/d/11DhyZULTP6giOeTa3UVSx5LweRJKTA_G/view?usp=sharing)

## Features

- **Live detection:** works with a laptop webcam or an RTSP stream (IP camera, or a phone app such as OctoStream).
- **Violation detection:** finds people without a helmet or without a safety vest and saves a snapshot of each case.
- **Telegram alerts:** sends a message with the violation photo to a personal chat or a group.
- **Web dashboard (Flask):**
  - live video with AI bounding boxes;
  - a violation log with photos;
  - a review status for each case (reviewed / not yet reviewed);
  - refresh the saved files and delete unneeded violation images.

## Model and Training

- **Model:** Ultralytics YOLO26n (nano), fine-tuned from the pretrained `yolo26n.pt` weights on a custom 4-class dataset of construction-site images.
- **Training platform:** Kaggle (GPU), August 2026. Notebook: **TODO: Kaggle notebook link, or remove this line**
- **Classes:** `0` Head, `1` Helmet, `2` Vest, `3` No-vest

### Training configuration

| Setting | Value |
| :--- | :--- |
| Base weights | `yolo26n.pt` (pretrained) |
| Model size | 2.5M parameters, 5.9 GFLOPs |
| Hardware / software | Kaggle Tesla T4 GPU, Ultralytics 8.4.115, PyTorch 2.10 |
| Epochs | 80 (early stopping, patience 15) |
| Batch size / image size | 32 / 640 |
| Optimizer | `auto` (Ultralytics default) |
| Augmentation (applied on the fly during training) | mosaic, mixup (0.2), copy-paste (0.3), HSV color shifts, horizontal flip (0.5), RandAugment, random erasing (0.4) |

### Dataset

The dataset was built in the Kaggle notebook by merging three labeled sources into one 4-class dataset (`head`, `helmet`, `vest`, `no-vest`).

| Source | Original images | Processing |
| :--- | :---: | :--- |
| Main dataset (`head`, `helmet`, `vest`) | 7,541 | Pruned to 4,000 images (3,541 redundant images removed) |
| Additional source 1 (`no-vest`) | 778 (622 train / 156 valid) | Offline augmentation: 2 extra copies per image |
| Additional source 2 | 2,322 (1,593 train / 478 valid / 251 test) | Offline augmentation: 2 extra copies per image |

- **Final split:** **TODO: N** training images and **TODO: N** validation images (see the `train:` and `val:` scan lines in the training log).
- **Sources and licenses:** **TODO: name and license of each dataset**

Annotated instances (individual labeled bounding boxes, not images):

| Class | Name | Training instances | Validation instances |
| :---: | :--- | :---: | :---: |
| 0 | Head | 24,577 | 4,781 |
| 1 | Helmet | 8,897 | 2,225 |
| 2 | Vest | 3,488 | 863 |
| 3 | No-vest | 8,066 | 2,166 |
| | **Total** | **45,028** | **10,035** |

### Results

All metrics are measured on the validation split. The first three values are the best result of each metric across the training epochs, so they come from different epochs. Training curves and other outputs are in the `Training_result/` folder.

| Metric | Value |
| :--- | :---: |
| mAP50 | 91.37% (epoch 62) |
| Precision | 88.48% (epoch 64) |
| Recall | 85.74% (epoch 73) |
| mAP50-95 | 57.30% |

![Training results](Training_result/results.png)

## Tech Stack

Python, Ultralytics YOLO26n, OpenCV, Flask, SQLite, Telegram Bot API

## Installation

Open a terminal in the project root folder and run the commands below.

### 1. Create the environment and install dependencies

```bash
# Create a virtual environment (if you do not have one yet)
python -m venv venv

# Activate it (Windows PowerShell)
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Set up the Telegram bot

1. **Bot token:** chat with `@BotFather` on Telegram, send `/newbot`, choose a display name and a username ending in `_bot`, then copy the token.
2. **Chat ID:** chat with `@userinfobot`, send `/start`, and copy your ID.
3. Create a file named `.env` in the project root with this content:

```env
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>
```

> On Windows, if you cannot create a file named `.env` directly, create `.env.txt`, edit it, then rename it to `.env`.
> **Never commit `.env` to GitHub.** It contains your private bot token and is excluded through `.gitignore`.

### 3. Run the web server

```bash
python app.py
```

Open the local address printed in the terminal (for example `http://127.0.0.1:5000/`) in Chrome or Edge.

## Usage

### A. Start the camera and detection

1. Open the web page.
2. Choose a video source:
   - **Webcam:** uses the camera of your computer.
   - **RTSP:** install the **OctoStream** app on your phone, copy the RTSP address it provides, and paste it into the web page.
3. The system starts the camera, runs live detection, and shows the video with bounding boxes on the page.
4. When a violation (no helmet or no vest) is detected, it is saved to the log and a photo is sent to Telegram.

### B. Review and manage violations

- **Violation log:** open the list to view the saved photos and mark whether each case has been reviewed.
- **Refresh saved files:** update the list with the latest data.
- **Delete unneeded images:** remove unnecessary violation photos to free storage.

## Project Structure

```text
PPE-Detection-YOLOv26/
├── app.py                  # Main entry point, Flask web server
├── detector_worker.py      # Background worker: AI detection and Telegram alerts
├── upgraded_no-vest.pt     # Trained YOLO26n weights (4 classes)
├── detections.db           # SQLite database of violation records
├── requirements.txt        # Python dependencies
├── static/                 # Web dashboard front-end (HTML, CSS, JavaScript)
├── Training_result/        # Training curves and metrics
└── readme.md
```

`.env` is created locally by each user (see Installation) and is not part of the repository.
