function setStatus(message) {
    document.getElementById("status").innerText = message || "";
}

function isHeicLike(file) {
    const name = String(file.name || "").toLowerCase();
    const type = String(file.type || "").toLowerCase();
    return (
        type.includes("heic") ||
        type.includes("heif") ||
        name.endsWith(".heic") ||
        name.endsWith(".heif")
    );
}

function showPreviewBlob(blob) {
    const preview = document.getElementById("preview");
    const placeholder = document.getElementById("placeholder");
    if (preview._objectUrl) {
        URL.revokeObjectURL(preview._objectUrl);
    }
    preview._objectUrl = URL.createObjectURL(blob);
    preview.src = preview._objectUrl;
    preview.style.display = "block";
    placeholder.style.display = "none";
}

function showHeicPlaceholder(fileName) {
    const preview = document.getElementById("preview");
    const placeholder = document.getElementById("placeholder");
    preview.style.display = "none";
    placeholder.style.display = "block";
    placeholder.querySelector("strong").innerText = fileName || "已选择图片";
    placeholder.querySelector("span").innerText = "HEIC 已选择，可直接发送；预览由电脑端生成。";
}

async function previewViaServer(file) {
    setStatus("正在由电脑生成预览...");
    const formData = new FormData();
    formData.append("token", uploadToken);
    formData.append("file", file);
    const response = await fetch("/preview", { method: "POST", body: formData });
    if (!response.ok) {
        let detail = "预览失败，但仍可发送。";
        try {
            const payload = await response.json();
            detail = payload.detail || detail;
        } catch (_error) {
            // ignore non-json errors
        }
        showHeicPlaceholder(file.name);
        setStatus(detail);
        return;
    }
    const blob = await response.blob();
    showPreviewBlob(blob);
    setStatus("");
}

async function previewImage() {
    const fileInput = document.getElementById("file-input");
    const preview = document.getElementById("preview");
    if (!fileInput.files || !fileInput.files[0]) {
        return;
    }
    const file = fileInput.files[0];
    if (isHeicLike(file)) {
        await previewViaServer(file);
        return;
    }

    const reader = new FileReader();
    reader.onload = event => {
        preview.onerror = async () => {
            preview.onerror = null;
            await previewViaServer(file);
        };
        preview.src = event.target.result;
        preview.style.display = "block";
        document.getElementById("placeholder").style.display = "none";
        setStatus("");
    };
    reader.readAsDataURL(file);
}

async function submitImage() {
    const fileInput = document.getElementById("file-input");
    if (!fileInput.files || !fileInput.files[0]) {
        alert("请先选择图片");
        return;
    }

    const button = document.getElementById("submit-btn");
    button.disabled = true;
    button.innerText = "发送中...";
    setStatus("图片正在发送到电脑端...");

    const formData = new FormData();
    formData.append("token", uploadToken);
    formData.append("file", fileInput.files[0]);

    try {
        const response = await fetch("/search", {
            method: "POST",
            body: formData
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
            throw new Error(payload.detail || "上传失败");
        }
        setStatus(payload.message || "已发送到电脑端，请查看 VideoSeek 搜索结果。");
    } catch (error) {
        setStatus(error.message || "连接失败，请确认和电脑在同一局域网。");
    } finally {
        button.disabled = false;
        button.innerText = "发送并搜索";
    }
}

function clearFile() {
    const preview = document.getElementById("preview");
    if (preview._objectUrl) {
        URL.revokeObjectURL(preview._objectUrl);
        preview._objectUrl = null;
    }
    document.getElementById("file-input").value = "";
    preview.removeAttribute("src");
    preview.style.display = "none";
    const placeholder = document.getElementById("placeholder");
    placeholder.style.display = "block";
    placeholder.querySelector("strong").innerText = "选择一张图片";
    placeholder.querySelector("span").innerText = "支持 JPG / PNG / HEIC（iPhone）";
    setStatus("");
}
