# Flashcard Trắc Nghiệm

Trang luyện flashcard local cho file Word có đáp án đúng được gạch chân.

## Cách dùng

1. Tạo dữ liệu từ file Word:

   ```powershell
   python scripts/import_docx.py "d:\hoc tap\tai chinh quoc te\test bank goc.docx"
   ```

2. Mở `index.html` bằng trình duyệt. Nếu muốn chạy qua server tĩnh:

   ```powershell
   python -m http.server 8000
   ```

3. Khi luyện:
   - Mặt trước không có underline.
   - Bấm `Show` để xem bản gốc có underline.
   - Tự bấm `Đúng` hoặc `Sai`.
   - Dùng `Làm lại câu sai` cho tới khi hết sai.

Tiến độ câu sai được lưu trong `localStorage` của trình duyệt.
