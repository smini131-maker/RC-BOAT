"""YOLOv5n ONNX detector: OpenCV DNN, single balloon class, static 320 input."""
import hashlib
import json
from pathlib import Path
import numpy as np

def verify_model(model_path, manifest_path, input_size):
    model, manifest = Path(model_path).expanduser(), Path(manifest_path).expanduser()
    if not model.is_file() or not manifest.is_file():
        raise ValueError("MODEL_MISSING: install trained ONNX and model_manifest.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("classes") != ["balloon"] or data.get("output_format") != "yolov5":
        raise ValueError("MODEL_CLASS_MISMATCH: expected one trained balloon class")
    if int(data.get("input_size", 0)) != int(input_size):
        raise ValueError("MODEL_INPUT_SIZE_MISMATCH")
    if hashlib.sha256(model.read_bytes()).hexdigest() != data.get("sha256"):
        raise ValueError("MODEL_HASH_MISMATCH")
    return data

def decode_predictions(prediction, original_shape, input_size, scale, padding, confidence, nms_iou, cv2):
    rows = np.asarray(prediction)
    if rows.ndim == 3 and rows.shape[0] == 1:
        rows = rows[0]
    if rows.ndim != 2 or rows.shape[1] != 6:
        raise ValueError("Expected YOLOv5 single-class output [1,N,6], got %s" % (rows.shape,))
    height, width = original_shape[:2]
    boxes, scores = [], []
    for row in rows[np.isfinite(rows).all(axis=1)]:
        score = float(row[4]*row[5])
        if score < confidence or row[2] <= 0 or row[3] <= 0:
            continue
        x, y, w, h = [float(value) for value in row[:4]]
        left = max(0, min(width, (x-w/2-padding[0])/scale))
        top = max(0, min(height, (y-h/2-padding[1])/scale))
        right = max(0, min(width, (x+w/2-padding[0])/scale))
        bottom = max(0, min(height, (y+h/2-padding[1])/scale))
        if right <= left or bottom <= top:
            continue
        boxes.append([left, top, right-left, bottom-top])
        scores.append(score)
    indices = cv2.dnn.NMSBoxes(boxes, scores, confidence, nms_iou) if boxes else []
    return [{"class_id": 0, "label": "balloon", "confidence": scores[int(i)],
             "bbox": [boxes[int(i)][0], boxes[int(i)][1],
                      boxes[int(i)][0]+boxes[int(i)][2], boxes[int(i)][1]+boxes[int(i)][3]]}
            for i in np.asarray(indices).reshape(-1)]

class BalloonDetector:
    def __init__(self, config):
        import cv2
        self.cv2, self.config = cv2, config
        self.manifest = verify_model(config["model_path"], config["model_manifest"], config["input_size"])
        model_bytes = Path(config["model_path"]).expanduser().read_bytes()
        self.net = cv2.dnn.readNetFromONNX(np.frombuffer(model_bytes, dtype=np.uint8))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        if self.net.empty():
            raise ValueError("ONNX network is empty")
        # Warm up before reporting model_ready.
        size = int(config["input_size"])
        self.detect(np.zeros((size, size, 3), dtype=np.uint8))

    def detect(self, frame):
        cv2, size = self.cv2, int(self.config["input_size"])
        height, width = frame.shape[:2]
        scale = min(size/width, size/height)
        rw, rh = round(width*scale), round(height*scale)
        left, top = (size-rw)//2, (size-rh)//2
        padded = np.full((size, size, 3), 114, dtype=np.uint8)
        padded[top:top+rh, left:left+rw] = cv2.resize(frame, (rw, rh))
        self.net.setInput(cv2.dnn.blobFromImage(padded, 1/255.0, (size, size), swapRB=True, crop=False))
        prediction = self.net.forward()
        return decode_predictions(prediction, frame.shape, size, scale, (left, top),
                                  self.config["confidence"], self.config["nms_iou"], cv2)
