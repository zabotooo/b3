import makeToolboxXML, {innerCategoryXML} from '../../../src/lib/make-toolbox-xml';

const ext = (id, name, blocks) => ({
    id,
    xml: `<category name="${name}" toolboxitemid="${id}" colour="#000" secondaryColour="#111">${blocks}</category>`
});

const categoryIds = xml => [...xml.matchAll(/<category\s[^>]*toolboxitemid="([^"]+)"/g)].map(m => m[1]);

describe('B3 toolbox', () => {
    test('has no Scratch stage categories', () => {
        const xml = makeToolboxXML(true);
        for (const id of ['motion', 'looks', 'sound', 'sensing']) {
            expect(categoryIds(xml)).not.toContain(id);
        }
    });

    test('orders B3 categories like SPIKE and merges extras into core ones', () => {
        const xml = makeToolboxXML(false, true, 'stage', [
            ext('flippersensors', 'Sensors', '<block type="flippersensors_color"/>'),
            ext('b3sensors', 'Sensors', '<block type="b3sensors_tiltDirection"/>'),
            ext('flippermotor', 'Motors', '<block type="flippermotor_motorStop"/>'),
            ext('flipperevents', 'Events', '<block type="flipperevents_whenProgramStarts"/>'),
            ext('b3events', 'Events', '<block type="b3events_whenTilted"/>'),
            ext('flippercontrol', 'Control', '<block type="flippercontrol_stopOtherStacks"/>'),
            ext('flipperoperator', 'Operators', '<block type="flipperoperator_isInBetween"/>'),
            ext('flippersound', 'Sound', '<block type="flippersound_beep"/>'),
            ext('b3light', 'Light', '<block type="b3light_off"/>'),
            ext('flipperlight', 'Light', '<block type="flipperlight_lightColorMatrixOff"/>'),
            ext('flippermove', 'Movement', '<block type="flippermove_stopMove"/>')
        ]);
        expect(categoryIds(xml)).toEqual([
            'flippermotor', 'flippermove', 'flipperlight', 'flippersound', 'flipperevents', 'control',
            'flippersensors', 'operators', 'variables', 'myBlocks'
        ]);
        const between = (from, to) => xml.slice(
            xml.indexOf(`toolboxitemid="${from}"`), xml.indexOf(`toolboxitemid="${to}"`));
        expect(between('flipperlight', 'flippersound')).toContain('b3light_off');
        const sound = between('flippersound', 'flipperevents');
        expect(sound).toContain('flippersound_beep');
        expect(sound).toContain('sound_setvolumeto');
        expect(sound).toContain('sound_changevolumeby');
        expect(sound).toContain('type="sound_volume"');
        const events = between('flipperevents', 'control');
        expect(events).toContain('flipperevents_whenProgramStarts');
        expect(events).toContain('b3events_whenTilted');
        expect(events).toContain('event_broadcast');
        expect(events).toContain('event_whenbroadcastreceived');
        const control = between('control', 'flippersensors');
        expect(control).toContain('control_wait');
        expect(control).toContain('flippercontrol_stopOtherStacks');
        expect(between('flippersensors', 'operators')).toContain('b3sensors_tiltDirection');
        expect(between('operators', 'variables')).toContain('flipperoperator_isInBetween');
    });

    test('innerCategoryXML strips the category wrapper', () => {
        expect(innerCategoryXML('<category name="x" id="y"><block type="a"/></category>'))
            .toBe('<block type="a"/>');
    });
});
