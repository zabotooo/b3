export const LOW_VIN = 7.0;

const wrap = n => ((Math.round(n) % 360) + 360) % 360;

const valueOf = device => {
    switch (device.kind) {
    case 'motor_abs': return `${wrap(device.aposition)}°`;
    case 'motor_rel': return `${wrap(device.position)}°`;
    case 'motor_passive': return `${device.power}%`;
    case 'color': return `${device.color === 'none' ? 'no color' : device.color} · ${device.reflection}%`;
    case 'color_distance':
        return `${device.color === 'none' ? 'no color' : device.color} · ${device.reflection}% · ${device.distance}`;
    case 'distance': return device.distance_mm < 0 ? '—' : `${device.distance_mm / 10} cm`;
    case 'force': return `${device.force_n.toFixed(1)} N`;
    case 'light': return `${device.brightness}%`;
    case 'wedo_tilt': return Array.isArray(device.tilt) ? device.tilt.join(', ') : '';
    case 'wedo_motion': return `${device.distance}`;
    default: return '';
    }
};

const describePort = (port, device) => {
    if (!device) return {title: port, value: 'empty'};
    return {title: `${port} · ${device.name}`, value: valueOf(device)};
};

export default describePort;
