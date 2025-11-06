document.addEventListener('DOMContentLoaded', () => {
    function initTable(tableId, addBtnId) {
        const table = document.getElementById(tableId);
        const addBtn = document.getElementById(addBtnId);
        if (!table || !addBtn) return;
        const tbody = table.querySelector('tbody');
        
        addBtn.addEventListener('click', () => {
            const first = tbody.querySelector('.item-row');
            const clone = first.cloneNode(true);
            clone.querySelectorAll('input').forEach(i => {
                if (i.type === 'number') i.value = 1;
                else i.value = '';
            });
            clone.querySelectorAll('select').forEach(s => s.selectedIndex = 0);
            tbody.appendChild(clone);
            attachRemove();
        });
        
        function attachRemove() {
            tbody.querySelectorAll('.remove-row').forEach(btn => {
                btn.onclick = (e) => {
                    const rows = tbody.querySelectorAll('.item-row');
                    if (rows.length <= 1) return;
                    e.target.closest('.item-row').remove();
                };
            });
        }
        attachRemove();
    }
    
    initTable('equipment-table', 'add-row');
    
    const saveMarathon = document.getElementById('save-marathon');
    if (saveMarathon) saveMarathon.onclick = async () => {
        const name = document.getElementById('new-marathon-name').value.trim();
        if (!name) return alert('Enter marathon name');
        const res = await fetch('/api/add_marathon', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const data = await res.json();
        document.querySelectorAll('#marathon-select,#marathon-select-return,select[name="marathon"]').forEach(s => {
            const opt = document.createElement('option');
            opt.value = data.id;
            opt.text = data.name;
            s.appendChild(opt);
            s.value = data.id; // Automatically select the new marathon
            // Trigger change event if this is the return page to reload unreturned items
            if (s.id === 'marathon-select-return') {
                s.dispatchEvent(new Event('change'));
            }
        });
        bootstrap.Modal.getInstance(document.getElementById('addMarathonModal')).hide();
        document.getElementById('new-marathon-name').value = ''; // Clear the input field
    };
    
    const saveStation = document.getElementById('save-station');
    if (saveStation) saveStation.onclick = async () => {
        const name = document.getElementById('new-station-name').value.trim();
        if (!name) return alert('Enter station name');
        const res = await fetch('/api/add_station', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const data = await res.json();
        document.querySelectorAll('#station-select,#station-select-return').forEach(s => {
            const opt = document.createElement('option');
            opt.value = data.id;
            opt.text = data.name;
            s.appendChild(opt);
            s.value = data.id; // Automatically select the new station
        });
        bootstrap.Modal.getInstance(document.getElementById('addStationModal')).hide();
        document.getElementById('new-station-name').value = ''; // Clear the input field
    };
    
    const saveEquipment = document.getElementById('save-equipment');
    if (saveEquipment) saveEquipment.onclick = async () => {
        const name = document.getElementById('new-equipment-name').value.trim();
        if (!name) return alert('Enter equipment name');
        const res = await fetch('/api/add_equipment', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const data = await res.json();
        document.querySelectorAll('select[name="equipment[]"]').forEach(s => {
            const opt = document.createElement('option');
            opt.value = data.id;
            opt.text = data.name;
            s.appendChild(opt);
        });
        bootstrap.Modal.getInstance(document.getElementById('addEquipmentModal')).hide();
        document.getElementById('new-equipment-name').value = ''; // Clear the input field
    };
    
    window.onMarathonChange = function() {
        const sel = document.getElementById('marathon-select-return');
        if (!sel) return;
        const marathon = sel.value;
        const params = new URLSearchParams(window.location.search);
        if (marathon) params.set('marathon', marathon);
        else params.delete('marathon');
        window.location.search = params.toString();
    };
});
