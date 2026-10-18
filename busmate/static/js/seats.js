const bus = document.getElementById('bus'), rid = bus.dataset.route, price = +bus.dataset.price;
const picked = new Set(), info = {}; let booked = {};
const neighbour = n => (n % 2 ? n + 1 : n - 1);      // 2+2 layout: (1,2) (3,4) ...
const isWindow = n => n % 4 === 1 || n % 4 === 0;
const word = g => g === 'F' ? 'a Female passenger' : g === 'M' ? 'a Male passenger' : 'Empty';
const info_el = document.getElementById('info');

function show(n) {
  const nb = neighbour(n), g = booked[nb];
  info_el.textContent = `Seat ${n}${isWindow(n) ? ' (window)' : ''}: neighbour seat ${nb} is ${g ? word(g) : 'Empty'}.`;
}
function draw() {
  bus.innerHTML = '';
  for (let r = 0; r < 10; r++) {
    const row = document.createElement('div'); row.className = 'brow';
    [1, 2, 0, 3, 4].forEach(k => {
      if (!k) { const a = document.createElement('div'); a.className = 'aisle'; row.append(a); return; }
      const n = r * 4 + k, s = document.createElement('div');
      s.className = 'seat' + (booked[n] ? ' b' + booked[n] : '') + (picked.has(n) ? ' picked' : '') +
        (document.getElementById('winOnly').checked && isWindow(n) && !booked[n] ? ' win' : '');
      s.textContent = n;
      s.onmouseover = () => show(n);
      s.onclick = () => {
        if (booked[n]) return;
        picked.has(n) ? picked.delete(n) : picked.add(n);
        show(n); draw(); renderPax();
      };
      row.append(s);
    });
    bus.append(row);
  }
}
function renderPax() {
  const box = document.getElementById('pax'); box.innerHTML = '';
  [...picked].sort((a, b) => a - b).forEach(n => {
    info[n] = info[n] || { name: '', gender: 'F' };
    const d = document.createElement('div');
    d.innerHTML = `Seat ${n}: <input placeholder="Passenger name" value="${info[n].name}" required>
      <select><option value="F">Female</option><option value="M">Male</option></select>`;
    const [i, s] = d.querySelectorAll('input,select'); s.value = info[n].gender;
    i.oninput = () => info[n].name = i.value; s.onchange = () => info[n].gender = s.value;
    box.append(d);
  });
  document.getElementById('total').textContent = picked.size * price;
}
document.getElementById('winOnly').onchange = draw;
document.getElementById('bookForm').onsubmit = () => {
  document.getElementById('data').value = JSON.stringify([...picked].map(n => ({ seat: n, ...info[n] })));
};
fetch('/api/seats/' + rid).then(r => r.json()).then(d => { booked = d; draw(); });
