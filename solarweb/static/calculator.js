/* SolarWeb Calculator: ước tính điện mặt trời theo hóa đơn điện. */
(function (root) {
	'use strict';

	var TIER_LIMITS = [50, 100, 200, 300, 400, Infinity];
	var INVERTERS_1P = [6, 8, 10, 12];
	var INVERTERS_3P = [8, 10, 12, 16, 20];
	var BATTERIES = [5, 10, 16, 20];
	var BATTERY_EFFICIENCY = 0.9;
	var BATTERY_KWH_PER_KWP = 2;

	/** Monthly kWh from a pre-VAT bill, walking EVN's progressive tiers. */
	function billToKwh(netBill, customer, c) {
		if (customer === 'commercial') return netBill / c.rate_commercial;
		if (customer === 'industrial') return netBill / c.rate_industrial;
		var kwh = 0, remaining = netBill, lower = 0;
		for (var i = 0; i < TIER_LIMITS.length; i++) {
			var tierCost = (TIER_LIMITS[i] - lower) * c.evn_tiers[i];
			if (remaining <= tierCost) return kwh + remaining / c.evn_tiers[i];
			kwh += TIER_LIMITS[i] - lower;
			remaining -= tierCost;
			lower = TIER_LIMITS[i];
		}
		return kwh;
	}

	function pricePerKwp(kwp, hybrid, c) {
		if (hybrid) {
			if (kwp <= 5) return c.hybrid_price_5;
			if (kwp <= 10) return c.hybrid_price_10;
			if (kwp <= 20) return c.hybrid_price_20;
			if (kwp <= 30) return c.hybrid_price_30;
			return c.hybrid_price_max;
		}
		if (kwp <= 5) return c.grid_price_5;
		if (kwp <= 10) return c.grid_price_10;
		return c.grid_price_max;
	}

	function phaseFactor(kwp, phase, c) {
		if (phase !== '3') return 1;
		if (kwp <= 10) return c.three_phase_factor_10;
		if (kwp <= 20) return c.three_phase_factor_20;
		return 1;
	}

	function firstAtLeast(list, value) {
		for (var i = 0; i < list.length; i++) if (list[i] >= value) return list[i];
		return null;
	}

	function paybackYears(price, yearlySavings, growth) {
		if (!price || yearlySavings <= 0) return null;
		if (!growth) return price / yearlySavings;
		return Math.log(1 + (price * growth) / yearlySavings) / Math.log(1 + growth);
	}

	/**
	 * input: { sunHours, bill, customer: residential|commercial|industrial,
	 *          phase: '1'|'3', roofType: metal|flat|tile, roofArea, nightRatio }
	 */
	function calculate(c, input) {
		var pr = c.performance_ratio;
		var vat = c.bill_vat || 0;
		var kwhMonth = billToKwh(input.bill / (1 + vat), input.customer, c);
		var dailyKwh = kwhMonth / 30;
		var m2PerKwp = c['roof_m2_' + input.roofType] || c.roof_m2_flat;

		var neededKwp = dailyKwh / (input.sunHours * pr);
		var roofKwp = input.roofArea / m2PerKwp;
		var roofLimited = roofKwp < neededKwp;
		var panels = Math.round((Math.min(neededKwp, roofKwp) * 1000) / c.panel_watt);
		var kwp = (panels * c.panel_watt) / 1000;

		var result = {
			kwhMonth: kwhMonth,
			neededKwp: neededKwp,
			roofMaxKwp: roofKwp,
			roofLimited: roofLimited,
			panels: panels,
			kwp: Math.round(kwp * 10) / 10,
			roofNeeded: Math.ceil(kwp * m2PerKwp),
			tooSmall: panels < 2
		};
		if (result.tooSmall) return result;

		// Hybrid only makes sense with heavy night use, a big enough system,
		// and daytime generation left over to charge the battery.
		var nightKwh = (input.nightRatio / 100) * dailyKwh;
		var dayKwh = dailyKwh - nightKwh;
		var dailyGeneration = kwp * input.sunHours * pr;
		var hybrid = input.nightRatio >= c.night_ratio_hybrid && kwp >= c.hybrid_min_kwp && dailyGeneration > dayKwh;
		var batteryKwh = 0, batteryLimited = false;
		if (hybrid) {
			var wanted = (roofLimited ? Math.max(0, dailyGeneration - dayKwh) : nightKwh) / BATTERY_EFFICIENCY;
			var cap = kwp * BATTERY_KWH_PER_KWP;
			batteryLimited = wanted > cap;
			var sized = Math.min(wanted, cap);
			batteryKwh = firstAtLeast(BATTERIES, sized) || Math.ceil(sized / 20) * 20;
		}
		var inverters = input.phase === '3' ? INVERTERS_3P : INVERTERS_1P;
		result.hybrid = hybrid;
		result.batteryKwh = batteryKwh;
		result.batteryLimited = batteryLimited;
		result.nightHeavySmall = input.nightRatio >= c.night_ratio_hybrid && kwp < c.hybrid_min_kwp;
		result.inverterKw = firstAtLeast(inverters, kwp * 0.6) || inverters[inverters.length - 1];
		result.dailyGeneration = dailyGeneration;

		// Price.
		var priceMin = null, priceMax = null;
		if (kwp > c.max_auto_kwp) {
			result.manualQuote = true;
		} else if (!hybrid && kwp <= c.package_max_kwp) {
			result.packageQuote = true;
			priceMin = priceMax = c.package_price;
		} else {
			var extraBattery = Math.max(0, batteryKwh - kwp * BATTERY_KWH_PER_KWP) * c.battery_price_kwh;
			var roofExtra = kwp * (c['roof_extra_' + input.roofType] || 0);
			var total = kwp * pricePerKwp(kwp, hybrid, c) * phaseFactor(kwp, input.phase, c) + extraBattery + roofExtra;
			priceMin = Math.round((total * 0.95) / 1e6) * 1e6;
			priceMax = Math.round((total * 1.05) / 1e6) * 1e6;
		}
		result.priceMin = priceMin;
		result.priceMax = priceMax;

		// Savings, valued at the customer's average rate including VAT.
		var avgRate = kwhMonth > 0 ? input.bill / kwhMonth : 0;
		var offsetKwh = Math.min(kwhMonth, dailyGeneration * 30);
		var monthlySavings = Math.round(offsetKwh * avgRate);
		var yearly = monthlySavings * 12;
		var g = c.price_growth;
		result.monthlySavings = monthlySavings;
		result.savingsPercent = input.bill > 0 ? Math.min(100, Math.round((monthlySavings / input.bill) * 100)) : 0;
		result.paybackFlat = [paybackYears(priceMin, yearly, 0), paybackYears(priceMax, yearly, 0)];
		result.paybackGrowth = [paybackYears(priceMin, yearly, g), paybackYears(priceMax, yearly, g)];
		result.savings25 = g ? (yearly * (Math.pow(1 + g, 25) - 1)) / g : yearly * 25;
		result.co2Tons = (kwp * input.sunHours * pr * 365 * c.co2_kg_per_kwh) / 1000;
		result.trees = Math.round((result.co2Tons * 1000) / 21 / 10) * 10;
		return result;
	}

	if (typeof module !== 'undefined' && module.exports) {
		module.exports = { calculate: calculate, billToKwh: billToKwh };
	}
	if (typeof document === 'undefined' || !root.SOLARWEB_CALC) return;

	/* ------------------------------------------------------------------ UI */

	var data = root.SOLARWEB_CALC;
	var config = data.config;
	Object.keys(config).forEach(function (k) {
		if (typeof config[k] === 'string' && config[k] !== '' && !isNaN(config[k])) config[k] = Number(config[k]);
	});

	var BILL_PRESETS = [[500000, '500k'], [1000000, '1 triệu'], [2000000, '2 triệu'], [3000000, '3 triệu'], [5000000, '5 triệu'], [10000000, '10 triệu']];
	var CUSTOMERS = [['residential', 'Hộ gia đình'], ['commercial', 'Kinh doanh'], ['industrial', 'Sản xuất']];
	var PHASES = [['1', '1 pha'], ['3', '3 pha']];
	var ROOFS = [['metal', 'Mái tôn'], ['flat', 'Mái bằng (bê tông)'], ['tile', 'Mái ngói']];

	function vnd(n) { return Math.round(n).toLocaleString('vi-VN') + 'đ'; }
	function million(n) { return (n / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 }); }
	function years(range) {
		if (range[0] == null) return '–';
		var a = range[0].toFixed(1).replace('.', ','), b = range[1].toFixed(1).replace('.', ',');
		return a === b ? a : a + '–' + b;
	}
	function el(tag, attrs, children) {
		var node = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (k) {
			if (k === 'text') node.textContent = attrs[k];
			else if (k === 'class') node.className = attrs[k];
			else node.setAttribute(k, attrs[k]);
		});
		(children || []).forEach(function (child) { if (child) node.appendChild(child); });
		return node;
	}
	function segmented(name, options, value, onChange) {
		var group = el('div', { class: 'swc-seg', role: 'radiogroup' });
		options.forEach(function (opt) {
			var btn = el('button', { type: 'button', class: 'swc-seg-btn', 'aria-pressed': String(opt[0] === value), text: opt[1] });
			btn.addEventListener('click', function () {
				group.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
				btn.setAttribute('aria-pressed', 'true');
				onChange(opt[0]);
			});
			group.appendChild(btn);
		});
		return group;
	}
	function field(label, control, hint) {
		return el('div', { class: 'swc-field' }, [el('div', { class: 'swc-label', text: label }), control, hint ? el('div', { class: 'swc-hint', text: hint }) : null]);
	}
	function stat(label, value, sub) {
		return el('div', { class: 'swc-stat' }, [el('div', { class: 'swc-stat-label', text: label }), el('div', { class: 'swc-stat-value', text: value }), sub ? el('div', { class: 'swc-stat-sub', text: sub }) : null]);
	}

	function mount(container) {
		var provinces = {};
		data.regions.forEach(function (r) { Object.keys(r.provinces).forEach(function (p) { provinces[p] = r.provinces[p]; }); });
		var state = { province: 'TP. Hồ Chí Minh', bill: 2000000, customer: 'residential', phase: '1', roofType: 'metal', roofArea: 60, nightRatio: 20 };
		var last = null;

		// Province.
		var select = el('select', { class: 'swc-input', 'aria-label': 'Tỉnh/thành' });
		data.regions.forEach(function (r) {
			var group = el('optgroup', { label: r.name });
			Object.keys(r.provinces).forEach(function (p) {
				var opt = el('option', { value: p, text: p });
				if (p === state.province) opt.selected = true;
				group.appendChild(opt);
			});
			select.appendChild(group);
		});
		select.addEventListener('change', function () { state.province = select.value; update(); });

		// Bill.
		var billInput = el('input', { class: 'swc-input swc-bill', type: 'text', inputmode: 'numeric', 'aria-label': 'Tiền điện mỗi tháng' });
		billInput.value = state.bill.toLocaleString('vi-VN');
		billInput.addEventListener('input', function () {
			var digits = billInput.value.replace(/\D/g, '');
			state.bill = Number(digits) || 0;
			billInput.value = digits ? state.bill.toLocaleString('vi-VN') : '';
			update();
		});
		var chips = el('div', { class: 'swc-chips' });
		BILL_PRESETS.forEach(function (p) {
			var chip = el('button', { type: 'button', class: 'swc-chip', text: p[1] });
			chip.addEventListener('click', function () { state.bill = p[0]; billInput.value = p[0].toLocaleString('vi-VN'); update(); });
			chips.appendChild(chip);
		});
		var billWrap = el('div', {}, [el('div', { class: 'swc-bill-wrap' }, [billInput, el('span', { class: 'swc-unit', text: 'đ/tháng' })]), chips]);

		// Roof area stepper.
		var area = el('input', { class: 'swc-input swc-area', type: 'number', min: '0', step: '5', inputmode: 'numeric', 'aria-label': 'Diện tích mái (m²)' });
		area.value = state.roofArea;
		area.addEventListener('input', function () { state.roofArea = Math.max(0, Number(area.value) || 0); update(); });
		function step(delta) {
			return function () { state.roofArea = Math.max(0, state.roofArea + delta); area.value = state.roofArea; update(); };
		}
		var minus = el('button', { type: 'button', class: 'swc-step', 'aria-label': 'Giảm 5 m²', text: '−' });
		var plus = el('button', { type: 'button', class: 'swc-step', 'aria-label': 'Tăng 5 m²', text: '+' });
		minus.addEventListener('click', step(-5));
		plus.addEventListener('click', step(5));
		var roofHint = el('div', { class: 'swc-hint' });

		// Night ratio.
		var night = el('input', { type: 'range', min: '0', max: '80', step: '5', class: 'swc-range', 'aria-label': 'Tỷ lệ dùng điện ban đêm' });
		night.value = state.nightRatio;
		var nightValue = el('strong', { text: state.nightRatio + '%' });
		night.addEventListener('input', function () { state.nightRatio = Number(night.value); nightValue.textContent = night.value + '%'; update(); });

		var form = el('div', { class: 'swc-form' }, [
			el('h2', { class: 'swc-title', text: 'Tính điện mặt trời theo hóa đơn' }),
			el('p', { class: 'swc-lead', text: 'Nhập tiền điện hằng tháng để ước tính công suất nên lắp, chi phí đầu tư và thời gian hoàn vốn.' }),
			field('Khu vực lắp đặt', select),
			field('Tiền điện trung bình mỗi tháng', billWrap),
			field('Bạn là', segmented('customer', CUSTOMERS, state.customer, function (v) { state.customer = v; update(); })),
			field('Điện lưới', segmented('phase', PHASES, state.phase, function (v) { state.phase = v; update(); })),
			field('Loại mái', segmented('roof', ROOFS, state.roofType, function (v) { state.roofType = v; update(); })),
			el('div', { class: 'swc-field' }, [el('div', { class: 'swc-label', text: 'Diện tích mái có thể lắp tấm pin' }), el('div', { class: 'swc-stepper' }, [minus, area, el('span', { class: 'swc-unit', text: 'm²' }), plus]), roofHint]),
			el('div', { class: 'swc-field' }, [el('div', { class: 'swc-label' }, [document.createTextNode('Điện dùng ban đêm: '), nightValue]), night, el('div', { class: 'swc-hint', text: 'Ví dụ: điều hòa phòng ngủ, bình nóng lạnh, sạc xe điện buổi tối.' })])
		]);

		// Only `results` is redrawn on input; the lead form stays mounted so typed
		// values and the Turnstile iframe survive.
		var results = el('div', { 'aria-live': 'polite' });
		var resultsPanel = el('div', { class: 'swc-results' }, [results]);
		container.textContent = '';
		container.appendChild(el('div', { class: 'swc-grid' }, [form, resultsPanel]));

		function render(r) {
			results.textContent = '';
			var empty = state.bill < 300000 || state.roofArea < 10 || r.tooSmall;
			leadForm.hidden = empty;
			if (empty) {
				results.appendChild(el('div', { class: 'swc-empty', text: state.roofArea < 10 ? 'Vui lòng nhập diện tích mái từ 10 m² trở lên.' : 'Hóa đơn dưới 300.000đ/tháng: lắp điện mặt trời thường chưa hiệu quả kinh tế. Hãy nhập hóa đơn thực tế của bạn.' }));
				return;
			}
			var priceText = r.manualQuote ? 'Cần khảo sát báo giá' : r.packageQuote ? million(r.priceMin) + ' triệu' : million(r.priceMin) + '–' + million(r.priceMax) + ' triệu';
			var priceSub = r.manualQuote ? 'Hệ trên ' + config.max_auto_kwp + ' kWp được thiết kế riêng' : r.packageQuote ? 'Gói trọn gói hòa lưới' : '±5% · chưa gồm khảo sát thực địa';

			results.appendChild(el('div', { class: 'swc-hero' }, [
				el('div', { class: 'swc-hero-label', text: 'Chi phí đầu tư dự kiến' }),
				el('div', { class: 'swc-hero-value', text: priceText }),
				el('div', { class: 'swc-hero-sub', text: priceSub })
			]));
			results.appendChild(el('div', { class: 'swc-stats' }, [
				stat('Công suất nên lắp', r.kwp.toLocaleString('vi-VN') + ' kWp', r.hybrid ? 'Hybrid có pin lưu trữ' : 'Hòa lưới bám tải'),
				stat('Số tấm pin', r.panels + ' tấm', config.panel_watt + ' Wp/tấm · ~' + r.roofNeeded + ' m² mái'),
				stat('Inverter', r.inverterKw + ' kW', state.phase === '3' ? '3 pha' : '1 pha'),
				stat('Pin lưu trữ', r.batteryKwh ? r.batteryKwh + ' kWh' : 'Không cần', r.batteryKwh ? 'Dùng điện mặt trời ban đêm' : 'Dùng điện chủ yếu ban ngày')
			]));
			results.appendChild(el('div', { class: 'swc-benefits' }, [
				stat('Tiết kiệm mỗi tháng', '~' + vnd(r.monthlySavings), '≈ ' + r.savingsPercent + '% hóa đơn hiện tại'),
				stat('Hoàn vốn', r.priceMin ? '~' + years(r.paybackGrowth) + ' năm' : '–', r.priceMin ? 'Giá điện tăng ' + Math.round(config.price_growth * 100) + '%/năm · ' + years(r.paybackFlat) + ' năm nếu giá giữ nguyên' : ''),
				stat('Lợi ích 25 năm', '~' + million(r.savings25) + ' triệu', 'Tổng tiền điện tiết kiệm'),
				stat('Giảm phát thải', r.co2Tons.toFixed(1).replace('.', ',') + ' tấn CO₂/năm', 'Tương đương ~' + r.trees.toLocaleString('vi-VN') + ' cây xanh')
			]));

			var notes = [];
			if (r.roofLimited) notes.push('Mái chỉ đủ cho khoảng ' + r.roofMaxKwp.toFixed(1).replace('.', ',') + ' kWp, nhỏ hơn nhu cầu ' + r.neededKwp.toFixed(1).replace('.', ',') + ' kWp. Hệ thống được giới hạn theo diện tích mái.');
			if (r.batteryLimited) notes.push('Nhu cầu điện ban đêm lớn hơn khả năng sạc của hệ. Kỹ thuật viên sẽ tư vấn thêm dung lượng pin khi khảo sát.');
			if (r.nightHeavySmall) notes.push('Bạn dùng nhiều điện ban đêm, nhưng hệ từ ' + config.hybrid_min_kwp + ' kWp trở lên mới nên lắp pin lưu trữ.');
			notes.push('Kết quả là ước tính sơ bộ. Giá chính xác phụ thuộc hướng mái, bóng che và thiết bị lựa chọn.');
			results.appendChild(el('ul', { class: 'swc-notes' }, notes.map(function (n) { return el('li', { text: n }); })));
		}

		// Lead form.
		var leadName = el('input', { class: 'swc-input', type: 'text', name: 'name', autocomplete: 'name', placeholder: 'Họ tên', required: 'required' });
		var leadPhone = el('input', { class: 'swc-input', type: 'tel', name: 'phone', autocomplete: 'tel', placeholder: 'Số điện thoại / Zalo', required: 'required' });
		var leadNote = el('input', { class: 'swc-input', type: 'text', name: 'note', placeholder: 'Địa chỉ lắp đặt, thời gian liên hệ… (không bắt buộc)' });
		var honeypot = el('input', { type: 'text', name: 'website', tabindex: '-1', autocomplete: 'off', class: 'swc-hp', 'aria-hidden': 'true' });
		var submit = el('button', { type: 'submit', class: 'swc-submit', text: 'Nhận tư vấn & báo giá chi tiết' });
		var message = el('div', { class: 'swc-message', role: 'status' });
		var zaloLink = data.zalo ? el('a', { class: 'swc-zalo', href: data.zalo, target: '_blank', rel: 'noopener', text: 'Chat Zalo ngay' }) : null;
		var consent = el('input', { type: 'checkbox', name: 'consent', required: 'required' });
		var consentText = [document.createTextNode(data.consent + ' ')];
		if (data.privacy) consentText.push(el('a', { href: data.privacy, target: '_blank', rel: 'noopener', text: 'Chính sách bảo mật' }));
		var consentLabel = el('label', { class: 'swc-consent' }, [consent, el('span', {}, consentText)]);
		var captchaBox = data.captcha ? el('div', { class: 'swc-captcha' }) : null;
		var leadForm = el('form', { class: 'swc-leadform', novalidate: 'novalidate' }, [
			el('h3', { text: 'Nhận phương án chi tiết miễn phí' }),
			el('p', { text: 'Kỹ thuật viên sẽ gọi lại để khảo sát mái và gửi báo giá chính xác.' }),
			leadName, leadPhone, leadNote, honeypot, consentLabel, captchaBox, submit, message, zaloLink
		]);
		resultsPanel.appendChild(leadForm);

		var captchaId = null;
		if (captchaBox && root.turnstile) {
			captchaId = root.turnstile.render(captchaBox, { sitekey: data.captcha, language: 'vi' });
		}

		leadForm.addEventListener('submit', function (e) {
			e.preventDefault();
			var phone = leadPhone.value.replace(/[^\d+]/g, '');
			var token = captchaId !== null ? root.turnstile.getResponse(captchaId) : '';
			var problem = !leadName.value.trim() || !/^\+?\d{9,12}$/.test(phone) ? 'Vui lòng nhập họ tên và số điện thoại hợp lệ.'
				: !consent.checked ? 'Vui lòng tick đồng ý để chúng tôi liên hệ tư vấn.'
				: captchaBox && !token ? 'Vui lòng hoàn tất xác minh chống spam.'
				: '';
			if (problem) {
				message.className = 'swc-message is-error';
				message.textContent = problem;
				return;
			}
			var r = last;
			var payload = {
				name: leadName.value.trim(),
				phone: phone,
				note: leadNote.value.trim(),
				website: honeypot.value,
				consent: consent.checked,
				turnstile: token,
				province: state.province,
				bill: vnd(state.bill),
				customer: (CUSTOMERS.filter(function (c) { return c[0] === state.customer; })[0] || [])[1] + ', ' + state.phase + ' pha, ' + (ROOFS.filter(function (x) { return x[0] === state.roofType; })[0] || [])[1] + ' ' + state.roofArea + ' m², ban đêm ' + state.nightRatio + '%',
				system: r && !r.tooSmall ? r.kwp + ' kWp, ' + r.panels + ' tấm, inverter ' + r.inverterKw + ' kW' + (r.batteryKwh ? ', pin ' + r.batteryKwh + ' kWh (hybrid)' : ' (hòa lưới)') : '',
				price: r && r.priceMin ? (r.packageQuote ? million(r.priceMin) : million(r.priceMin) + '–' + million(r.priceMax)) + ' triệu' : (r && r.manualQuote ? 'Cần khảo sát' : ''),
				savings: r && r.monthlySavings ? vnd(r.monthlySavings) + ' (' + r.savingsPercent + '%)' : '',
				payback: r && r.priceMin ? years(r.paybackGrowth) + ' năm' : ''
			};
			submit.disabled = true;
			message.className = 'swc-message';
			message.textContent = 'Đang gửi…';
			// No X-WP-Nonce: the endpoint is public, and a nonce baked into a
			// page-cached HTML expires and would make every submission fail.
			fetch(data.leadUrl, {
				method: 'POST',
				credentials: 'omit',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			}).then(function (res) {
				return res.json().then(function (body) { if (!res.ok) throw new Error(body.message || 'Lỗi gửi yêu cầu'); return body; });
			}).then(function () {
				message.className = 'swc-message is-success';
				message.textContent = 'Đã nhận yêu cầu! Chúng tôi sẽ liên hệ trong vòng 24 giờ.';
				leadForm.reset();
			}).catch(function (err) {
				message.className = 'swc-message is-error';
				message.textContent = err.message;
			}).then(function () {
				submit.disabled = false;
				// Tokens are single-use.
				if (captchaId !== null) root.turnstile.reset(captchaId);
			});
		});

		function update() {
			var areaPerKwp = config['roof_m2_' + state.roofType];
			roofHint.textContent = state.roofArea >= 10 ? 'Mái này lắp tối đa khoảng ' + (state.roofArea / areaPerKwp).toFixed(1).replace('.', ',') + ' kWp.' : '';
			last = calculate(config, {
				sunHours: provinces[state.province],
				bill: state.bill,
				customer: state.customer,
				phase: state.phase,
				roofType: state.roofType,
				roofArea: state.roofArea,
				nightRatio: state.nightRatio
			});
			render(last);
		}
		update();
	}

	function init() {
		document.querySelectorAll('[data-solarweb-calculator]').forEach(mount);
	}
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
	else init();
})(typeof window !== 'undefined' ? window : this);
