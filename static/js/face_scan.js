/**
 * Start webcam, capture frame to canvas, return data URL (JPEG).
 */
function startWebcam(videoEl, onError) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (onError) onError("Camera not supported in this browser.");
    return;
  }
  navigator.mediaDevices
    .getUserMedia({ video: { facingMode: "user" }, audio: false })
    .then(function (stream) {
      videoEl.srcObject = stream;
    })
    .catch(function () {
      if (onError) onError("Could not access webcam.");
    });
}

function stopWebcam(videoEl) {
  if (videoEl && videoEl.srcObject) {
    videoEl.srcObject.getTracks().forEach(function (t) {
      t.stop();
    });
    videoEl.srcObject = null;
  }
}

function captureDataUrl(videoEl, quality) {
  quality = quality || 0.85;
  var c = document.createElement("canvas");
  c.width = videoEl.videoWidth;
  c.height = videoEl.videoHeight;
  if (!c.width || !c.height) return null;
  var ctx = c.getContext("2d");
  ctx.drawImage(videoEl, 0, 0);
  return c.toDataURL("image/jpeg", quality);
}

/**
 * Turn a data URL from captureDataUrl into a File for multipart form upload.
 */
function dataUrlToJpegFile(dataUrl, filename) {
  if (!dataUrl || dataUrl.indexOf("base64,") < 0) return null;
  var parts = dataUrl.split(",");
  var mime = parts[0].match(/:(.*?);/);
  mime = mime ? mime[1] : "image/jpeg";
  var bstr = atob(parts[1]);
  var n = bstr.length;
  var u8 = new Uint8Array(n);
  while (n--) u8[n] = bstr.charCodeAt(n);
  return new File([u8], filename || "capture.jpg", { type: mime });
}
