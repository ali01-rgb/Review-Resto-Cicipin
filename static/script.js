document.addEventListener('DOMContentLoaded', function() {

    // ==========================================
    // 1. LOGIKA TOMBOL SCROLL DINAMIS (ATAS/BAWAH)
    // ==========================================
    const fab = document.querySelector('.fab-scroll');
    
    if (fab) {
        // Set awal tombol mengarah ke bawah
        fab.onclick = () => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });

        window.addEventListener('scroll', () => {
            // Hitung persentase scroll
            const scrollPercent = (window.scrollY + window.innerHeight) / document.documentElement.scrollHeight;
            
            if (scrollPercent > 0.6) {
                // Jika sudah melewati 60% halaman, putar tombol jadi ke atas
                fab.classList.add('is-bottom');
                fab.onclick = () => window.scrollTo({ top: 0, behavior: 'smooth' });
            } else {
                // Jika masih di atas, biarkan tombol mengarah ke bawah
                fab.classList.remove('is-bottom');
                fab.onclick = () => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            }
        });
    }

    // ==========================================
    // 2. LOGIKA DRAG AND DROP GAMBAR
    // ==========================================
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('image');
    const previewImage = document.getElementById('preview-image');
    const uploadText = document.getElementById('upload-text');

    if (dropZone && fileInput) {
        // Efek visual saat gambar diseret masuk
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover-active');
        });

        // Hapus efek saat gambar keluar area
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover-active');
        });

        // Logika saat gambar dilepas (Drop)
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover-active');
            
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                updatePreview();
            }
        });

        // Logika saat memilih file lewat klik biasa
        fileInput.addEventListener('change', updatePreview);

        function updatePreview() {
            if (fileInput.files && fileInput.files[0]) {
                const reader = new FileReader();
                
                reader.onload = function(e) {
                    previewImage.src = e.target.result;
                    previewImage.style.display = 'block';
                    if (uploadText) {
                        uploadText.style.display = 'none';
                    }
                }
                
                reader.readAsDataURL(fileInput.files[0]);
            }
        }
    }

    // ==========================================
    // 3. AUTO-HIDE POPUP NOTIFIKASI
    // ==========================================
    const popups = document.querySelectorAll('.popup');
    popups.forEach(popup => {
        if (popup.classList.contains('show')) {
            setTimeout(() => {
                popup.classList.remove('show');
            }, 3000);
        }
    });

});