export const LOW_VIN = 7.0;

const wrap = n => ((Math.round(n) % 360) + 360) % 360;

const joined = (...parts) => parts.filter(p => p !== null).join(' · ');
const pct = v => (typeof v === 'number' ? `${v}%` : null);
const colorName = c => {
    if (typeof c !== 'string') return null;
    return c === 'none' ? 'no color' : c;
};

// idle: hatd reads only the color mode while no program runs, other values would be old
const valueOf = (device, idle) => {
    switch (device.kind) {
    case 'motor_abs': return `${wrap(device.aposition)}°`;
    case 'motor_rel': return `${wrap(device.position)}°`;
    case 'motor_passive': return `${device.power}%`;
    case 'color':
        return idle ? joined(colorName(device.color)) : joined(colorName(device.color), pct(device.reflection));
    case 'color_distance':
        if (idle) return joined(colorName(device.color));
        return joined(colorName(device.color), pct(device.reflection),
            typeof device.distance === 'number' ? `${device.distance}` : null);
    case 'distance': return device.distance_mm < 0 ? '—' : `${device.distance_mm / 10} cm`;
    case 'force': return `${device.force_n.toFixed(1)} N`;
    case 'light': return `${device.brightness}%`;
    case 'wedo_tilt': return Array.isArray(device.tilt) ? device.tilt.join(', ') : '';
    case 'wedo_motion': return `${device.distance}`;
    default: return '';
    }
};

const describePort = (port, device, idle = false) => {
    if (!device) return {title: port, value: 'empty'};
    return {title: `${port} · ${device.name}`, value: valueOf(device, idle)};
};

export default describePort;
