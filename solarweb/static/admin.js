(function () {
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrf = csrfMeta ? csrfMeta.content : '';

    // Confirm before destructive submits: <form data-confirm="...">
    document.addEventListener('submit', function (e) {
        var msg = e.target.getAttribute('data-confirm');
        if (msg && !window.confirm(msg)) e.preventDefault();
    });

    // Repeating rows (spec attributes): a <tbody data-rows> with .row-item rows,
    // a [data-add-row="tbodyId"] button and .remove-row buttons
    document.querySelectorAll('[data-add-row]').forEach(function (btn) {
        var tbody = document.getElementById(btn.getAttribute('data-add-row'));
        if (!tbody) return;
        btn.addEventListener('click', function () {
            var template = tbody.querySelector('.row-item');
            var clone = template.cloneNode(true);
            clone.querySelectorAll('input').forEach(function (i) { i.value = ''; });
            clone.querySelectorAll('select').forEach(function (s) { s.selectedIndex = 0; });
            tbody.appendChild(clone);
            var first = clone.querySelector('input');
            if (first) first.focus();
        });
        tbody.addEventListener('click', function (e) {
            if (!e.target.classList.contains('remove-row')) return;
            var rows = tbody.querySelectorAll('.row-item');
            var row = e.target.closest('.row-item');
            if (rows.length > 1) row.remove();
            else row.querySelectorAll('input').forEach(function (i) { i.value = ''; });
        });
    });

    // Rich-text editors: <div data-editor="hiddenInputId">existing html</div>
    if (window.Quill) {
        document.querySelectorAll('[data-editor]').forEach(function (holder) {
            var input = document.getElementById(holder.getAttribute('data-editor'));
            var quill = new Quill(holder, {
                theme: 'snow',
                modules: {
                    toolbar: {
                        container: [
                            [{ header: [2, 3, 4, false] }],
                            ['bold', 'italic', 'underline', 'strike'],
                            [{ list: 'ordered' }, { list: 'bullet' }],
                            [{ align: [] }],
                            ['link', 'image', 'blockquote'],
                            ['clean']
                        ],
                        handlers: { image: function () { uploadImage(quill); } }
                    }
                }
            });
            var form = holder.closest('form');
            if (form) form.addEventListener('submit', function () { input.value = quill.root.innerHTML; });
        });
    }

    // Upload editor images to /admin/media/anh instead of embedding base64 data
    function uploadImage(quill) {
        var picker = document.createElement('input');
        picker.type = 'file';
        picker.accept = 'image/jpeg,image/png,image/webp';
        picker.onchange = function () {
            if (!picker.files.length) return;
            var body = new FormData();
            body.append('file', picker.files[0]);
            fetch(window.ADMIN_UPLOAD_URL, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: body })
                .then(function (res) { return res.json().then(function (data) { if (!res.ok) throw new Error(data.error || 'Lỗi tải ảnh'); return data; }); })
                .then(function (data) {
                    var range = quill.getSelection(true);
                    quill.insertEmbed(range ? range.index : quill.getLength(), 'image', data.url, 'user');
                })
                .catch(function (err) { alert(err.message); });
        };
        picker.click();
    }

    // Auto-slug preview: <input data-slug-source> fills an empty <input data-slug-target>
    var source = document.querySelector('[data-slug-source]');
    var target = document.querySelector('[data-slug-target]');
    if (source && target) {
        source.addEventListener('input', function () {
            if (target.dataset.touched) return;
            target.placeholder = slugify(source.value);
        });
        target.addEventListener('input', function () { target.dataset.touched = '1'; });
    }
    function slugify(text) {
        return text.replace(/đ/g, 'd').replace(/Đ/g, 'D').normalize('NFKD').replace(/[̀-ͯ]/g, '')
            .replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase();
    }
})();
