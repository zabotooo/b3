import describePort from '../../../src/components/b3-bar/describe-port';

describe('describePort', () => {
    test('empty port', () => {
        expect(describePort('A', null)).toEqual({title: 'A', value: 'empty'});
    });
    test('motors', () => {
        expect(describePort('A', {kind: 'motor_abs', name: 'Large Angular Motor (Grey)', aposition: -90}))
            .toEqual({title: 'A · Large Angular Motor (Grey)', value: '270°'});
        expect(describePort('B', {kind: 'motor_rel', name: 'Technic XL Motor', position: 725}))
            .toEqual({title: 'B · Technic XL Motor', value: '5°'});
        expect(describePort('C', {kind: 'motor_passive', name: 'Train Motor', power: -40}))
            .toEqual({title: 'C · Train Motor', value: '-40%'});
    });
    test('sensors', () => {
        expect(describePort('A', {kind: 'color_distance',
            name: 'Color & Distance Sensor',
            color: 'red',
            reflection: 4,
            distance: 5})).toEqual({title: 'A · Color & Distance Sensor', value: 'red · 4% · 5'});
        expect(describePort('B', {kind: 'distance', name: 'Distance Sensor', distance_mm: -1}))
            .toEqual({title: 'B · Distance Sensor', value: '—'});
        expect(describePort('B', {kind: 'distance', name: 'Distance Sensor', distance_mm: 123}))
            .toEqual({title: 'B · Distance Sensor', value: '12.3 cm'});
        expect(describePort('C', {kind: 'force', name: 'Force Sensor', force_n: 2.25, pressed: true}))
            .toEqual({title: 'C · Force Sensor', value: '2.3 N'});
        expect(describePort('D', {kind: 'color', name: 'Color Sensor', color: 'none', reflection: 0}))
            .toEqual({title: 'D · Color Sensor', value: 'no color · 0%'});
        expect(describePort('A', {kind: 'color_distance', name: 'Color & Distance Sensor', color: 'red'}))
            .toEqual({title: 'A · Color & Distance Sensor', value: 'red'});
    });
    test('idle color sensors show only the color hatd keeps reading', () => {
        const cd = {kind: 'color_distance', name: 'Color & Distance Sensor', color: 'red', reflection: 4, distance: 5};
        expect(describePort('A', cd, true)).toEqual({title: 'A · Color & Distance Sensor', value: 'red'});
        expect(describePort('D', {kind: 'color', name: 'Color Sensor', color: 'none', reflection: 0}, true))
            .toEqual({title: 'D · Color Sensor', value: 'no color'});
    });
    test('unknown kind shows the name only', () => {
        expect(describePort('D', {kind: null, name: 'Unknown device 99'}))
            .toEqual({title: 'D · Unknown device 99', value: ''});
    });
});
