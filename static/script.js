// ============ CAMERA (MỚI THÊM) ============
function getSelectedSource() {
    const sourceType = document.getElementById('sourceType').value;
    const sourceInput = document.getElementById('sourceInput').value.trim();

    if (sourceType === 'webcam') {
        return "0";
    }
    // Với 'rtsp' hoặc 'file' -> lấy đúng nội dung người dùng gõ
    return sourceInput;
}

async function startCamera() {
    const btnStart = document.getElementById('btnStartCamera');
    const btnStop = document.getElementById('btnStopCamera');
    const statusEl = document.getElementById('cameraStatus');
    const videoContainer = document.getElementById('videoContainer');
    const videoFeed = document.getElementById('videoFeed');

    const source = getSelectedSource();
    if (!source) {
        alert("Vui lòng nhập nguồn video (RTSP URL hoặc đường dẫn file)!");
        return;
    }

    btnStart.disabled = true;
    statusEl.textContent = "Trạng thái: Đang khởi động...";

    try {
        const resp = await fetch('/api/camera/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: source })
        });
        const data = await resp.json();

        if (!data.started) {
            statusEl.textContent = "Lỗi: " + (data.message || "Không khởi động được");
            btnStart.disabled = false;
            return;
        }

        videoFeed.src = '/video_feed?t=' + Date.now();
        videoContainer.style.display = 'block';
        btnStop.disabled = false;
        statusEl.textContent = "Trạng thái: " + (data.status_text || "Đang chạy");
    } catch (e) {
        statusEl.textContent = "Lỗi khởi động camera!";
        btnStart.disabled = false;
        console.error(e);
    }
}

async function stopCamera() {
    const btnStart = document.getElementById('btnStartCamera');
    const btnStop = document.getElementById('btnStopCamera');
    const statusEl = document.getElementById('cameraStatus');
    const videoContainer = document.getElementById('videoContainer');
    const videoFeed = document.getElementById('videoFeed');

    try {
        await fetch('/api/camera/stop', { method: 'POST' });
        videoFeed.src = '';
        videoContainer.style.display = 'none';
        btnStart.disabled = false;
        btnStop.disabled = true;
        statusEl.textContent = "Trạng thái: Đã tắt";
    } catch (e) {
        console.error(e);
    }
}

async function checkCameraStatusOnLoad() {
    try {
        const resp = await fetch('/api/camera/status');
        const data = await resp.json();
        if (data.running) {
            document.getElementById('videoFeed').src = '/video_feed?t=' + Date.now();
            document.getElementById('videoContainer').style.display = 'block';
            document.getElementById('btnStartCamera').disabled = true;
            document.getElementById('btnStopCamera').disabled = false;
            document.getElementById('cameraStatus').textContent = "Trạng thái: " + data.status_text;
        }
    } catch (e) {
        console.error(e);
    }
}
// ============ HẾT PHẦN CAMERA ============


// Cập nhật thời gian hệ thống
setInterval(() => {
    document.getElementById('sys-time').textContent = new Date().toLocaleTimeString('vi-VN');
}, 1000);

// Khởi chạy khi load trang
document.addEventListener("DOMContentLoaded", () => {
    loadStats();
    loadDetections();
    checkCameraStatusOnLoad();
    setInterval(loadStats, 10000);

    document.getElementById('btnStartCamera').addEventListener('click', startCamera);
    document.getElementById('btnStopCamera').addEventListener('click', stopCamera);

    // MỚI THÊM: Hiện/ẩn ô nhập RTSP/file tùy loại nguồn được chọn
    const sourceTypeEl = document.getElementById('sourceType');
    const sourceInputEl = document.getElementById('sourceInput');
    sourceTypeEl.addEventListener('change', () => {
        if (sourceTypeEl.value === 'webcam') {
            sourceInputEl.style.display = 'none';
        } else if (sourceTypeEl.value === 'rtsp') {
            sourceInputEl.style.display = 'block';
            sourceInputEl.placeholder = "Ví dụ: rtsp://admin:matkhau@192.168.1.100:554/stream1";
        } else {
            sourceInputEl.style.display = 'block';
            sourceInputEl.placeholder = "Ví dụ: C:/videos/test.mp4";
        }
    });
});

// GỌI API: Lấy thống kê
async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('stat-total').innerText = data.total;
        document.getElementById('stat-today').innerText = data.today;
        document.getElementById('stat-week').innerText = data.this_week;
        document.getElementById('stat-unreviewed').innerText = data.unreviewed;
    } catch (err) {
        console.error("Lỗi tải thống kê:", err);
    }
}

// GỌI API: Lấy danh sách phát hiện
async function loadDetections() {
    try {
        const res = await fetch('/api/detections?limit=50');
        const data = await res.json();
        const tbody = document.getElementById('detections-list');
        tbody.innerHTML = '';

        data.items.forEach(item => {
            const date = new Date(item.timestamp).toLocaleString('vi-VN');
            const statusClass = item.status === 'unreviewed' ? 'tag-unreviewed' : 'tag-reviewed';
            const statusText = item.status === 'unreviewed' ? 'Chưa xem' : 'Đã duyệt';
            
            const tr = document.createElement('tr');
            tr.onclick = () => viewDetail(item);
            tr.innerHTML = `
                <td>${date}</td>
                <td><b>${item.camera_source || 'Unknown'}</b><br><small style="color:var(--text-muted)">${item.address}</small></td>
                <td>${item.confidence ? item.confidence + '%' : 'N/A'}</td>
                <td><span class="tag ${statusClass}">${statusText}</span></td>
                <td>
                    <button class="btn btn-sm" onclick="event.stopPropagation(); toggleStatus(${item.id}, '${item.status}')">
                        Đổi TT
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteRecord(${item.id})">
                        Xóa
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Lỗi tải danh sách:", err);
    }
}

// Hiển thị chi tiết bên khung phải
function viewDetail(item) {
    const detailPanel = document.getElementById('detail-content');
    const date = new Date(item.timestamp).toLocaleString('vi-VN');
    const imgHtml = item.image_url ? `<img src="${item.image_url}" alt="Hình ảnh phát hiện">` : '<div style="padding:40px; background:#1e293b; text-align:center; margin-top:15px; border:1px solid #334155; border-radius:6px;">Không có hình ảnh</div>';
    
    detailPanel.innerHTML = `
        <div class="detail-card">
            <p style="color:var(--accent); font-weight:bold; font-size:1.2rem;">ID: #${item.id}</p>
            <p><b>Thời gian:</b> ${date}</p>
            <p><b>Vị trí:</b> ${item.address}</p>
            <p><b>Camera:</b> ${item.camera_source || 'Không rõ'}</p>
            <p><b>Số người:</b> ${item.person_count}</p>
            <p><b>Độ tin cậy (AI):</b> ${item.confidence ? item.confidence + '%' : 'Không có'}</p>
            <p><b>Ghi chú:</b> ${item.notes || 'Không có'}</p>
            ${imgHtml}
            
            <div class="detail-actions">
                <button class="btn" onclick="toggleStatus(${item.id}, '${item.status}')">Đánh dấu Đã duyệt / Chưa xem</button>
            </div>
        </div>
    `;
}

// GỌI API: Cập nhật trạng thái
async function toggleStatus(id, currentStatus) {
    const newStatus = currentStatus === 'unreviewed' ? 'reviewed' : 'unreviewed';
    try {
        await fetch(`/api/detections/${id}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        loadDetections();
        loadStats();
        document.getElementById('detail-content').innerHTML = '<div class="detail-placeholder">Chọn một sự kiện để xem chi tiết và hình ảnh</div>';
    } catch (err) {
        alert("Lỗi khi cập nhật trạng thái!");
    }
}

// GỌI API: Xóa bản ghi
async function deleteRecord(id) {
    if(!confirm("Bạn có chắc chắn muốn xóa bản ghi này và hình ảnh kèm theo không?")) return;
    try {
        await fetch(`/api/detections/${id}`, { method: 'DELETE' });
        loadDetections();
        loadStats();
        document.getElementById('detail-content').innerHTML = '<div class="detail-placeholder">Chọn một sự kiện để xem chi tiết và hình ảnh</div>';
    } catch (err) {
        alert("Lỗi khi xóa!");
    }
}