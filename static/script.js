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
        params.delete('station'); // Clear station filter when marathon changes
        window.location.search = params.toString();
    };

    // Function to handle station selection change - maintains selection and updates list
    window.onStationChange = function() {
        const marathonSel = document.getElementById('marathon-select-return');
        const stationSel = document.getElementById('station-select-return');
        if (!marathonSel || !stationSel) return;
        
        const marathon = marathonSel.value;
        const station = stationSel.value;
        const selectedOption = stationSel.options[stationSel.selectedIndex];
        
        // Build query parameters
        const params = new URLSearchParams(window.location.search);
        if (marathon) params.set('marathon', marathon);
        else params.delete('marathon');
        
        // Handle station - if not placeholder, include station param
        if (station && selectedOption) {
            params.set('station', station);
        } else {
            params.delete('station');
        }
        
        window.location.search = params.toString();
    };

    // Return form submission handler
    const returnForm = document.getElementById('return-form');
    if (returnForm) {
        returnForm.onsubmit = function(e) {
            // Check if we should use the person selection or username
            const personSelect = document.getElementById('person-select-return');
            const newPersonInput = returnForm.querySelector('input[name="new_person"]');
            if (personSelect && personSelect.value) {
                newPersonInput.value = ''; // Clear new person if one was selected
            }
            
            // If no station is selected but there's one unreturned item selected to return,
            // use that item's station instead
            const stationSelect = document.getElementById('station-select-return');
            if (stationSelect && !stationSelect.value) {
                const quantities = returnForm.querySelectorAll('input[name="quantity[]"]');
                const stationCells = returnForm.querySelectorAll('#return-table tbody tr td:first-child');
                let selectedStation = null;
                
                for (let i = 0; i < quantities.length; i++) {
                    if (quantities[i].value > 0) {
                        const stationName = stationCells[i].textContent.trim();
                        if (stationName && stationName !== '—') {
                            // Find matching station ID from select options
                            for (const opt of stationSelect.options) {
                                if (opt.textContent === stationName) {
                                    stationSelect.value = opt.value;
                                    break;
                                }
                            }
                            break;
                        }
                    }
                }
            }
            
            return true; // Allow form submission to continue
        };
    }
});