import {readFileSync} from 'node:fs';
import {test, expect} from '@playwright/test';

const PIN = process.env.B3_PIN || '1234';
const MOTOR = process.env.B3_MOTOR || 'A';

const login = async page => {
    await page.goto('/');
    await page.getByLabel('Robot PIN').fill('0000');
    await page.getByRole('button', {name: 'Connect'}).click();
    await expect(page.getByText('Wrong PIN')).toBeVisible();
    await page.getByLabel('Robot PIN').fill(PIN);
    await page.getByRole('button', {name: 'Connect'}).click();
    await expect(page.getByText('Connected', {exact: true})).toBeVisible();
};

test('B3 editor drives a motor through hatd', async ({page}) => {
    await login(page);
    // no Scratch community features, English only
    for (const text of ['Share', 'See Project Page', 'Tutorials', 'Debug']) {
        await expect(page.getByText(text, {exact: true})).toHaveCount(0);
    }
    await expect(page.getByPlaceholder('Project title here')).toHaveValue('B3 Project');
    // no Scratch stage, sprites or logo (scratch-blocks keeps a hidden text-measuring canvas)
    await expect(page.locator('canvas:not(.blocklyComputeCanvas)')).toHaveCount(0);
    await expect(page.getByAltText('Scratch')).toHaveCount(0);
    // B3 categories in the palette
    for (const name of ['Motors', 'Movement', 'Light', 'Sound', 'Events', 'Control', 'Sensors', 'Operators']) {
        await expect(page.getByRole('treeitem', {name, exact: true})).toBeVisible();
    }
    // Sounds tab: the stage's sounds; only upload (and record on https), no Scratch library
    await page.getByRole('tab', {name: 'Sounds'}).click();
    await expect(page.getByRole('region', {name: 'Sounds editor panel'}).getByText('pop', {exact: true})
        .first())
        .toBeVisible();
    await expect(page.locator('[aria-label="Choose a Sound"]')).toHaveCount(0);
    await expect(page.locator('[aria-label="Surprise"]')).toHaveCount(0);
    await expect(page.locator('[aria-label="Upload Sound"]')).toHaveCount(1);
    await page.getByRole('tab', {name: 'Code'}).click();
    // port bar shows the devices
    await expect(page.getByText(`${MOTOR} ·`)).toBeVisible();

    // Run needs control
    await expect(page.getByTitle('Take control first')).toBeDisabled();
    await page.getByRole('button', {name: /Take control/}).click();
    await expect(page.getByText('You control the robot')).toBeVisible();

    // "when program starts → MOTOR run clockwise for 1 rotations"
    const before = await page.evaluate(m => window.b3vm.b3hub.device(m).position, MOTOR);
    await page.evaluate(m => {
        const vm = window.b3vm;
        const stage = vm.runtime.getTargetForStage();
        stage.blocks.createBlock({id: 'hat',
            opcode: 'flipperevents_whenProgramStarts',
            topLevel: true,
            next: 'run',
            inputs: {},
            fields: {},
            parent: null,
            shadow: false});
        stage.blocks.createBlock({id: 'run',
            opcode: 'flippermotor_motorTurnForDirection',
            topLevel: false,
            parent: 'hat',
            next: null,
            shadow: false,
            inputs: {},
            fields: {
                PORT: {name: 'PORT', value: m},
                DIRECTION: {name: 'DIRECTION', value: 'clockwise'},
                UNIT: {name: 'UNIT', value: 'rotations'}}});
        stage.blocks.createBlock({id: 'val',
            opcode: 'math_number',
            topLevel: false,
            parent: 'run',
            shadow: true,
            fields: {NUM: {name: 'NUM', value: '1'}},
            inputs: {},
            next: null});
        stage.blocks.getBlock('run').inputs.VALUE = {name: 'VALUE', block: 'val', shadow: 'val'};
    }, MOTOR);
    await page.getByTitle('Run').click();
    await expect.poll(() => page.evaluate(m => window.b3vm.b3hub.device(m).position, MOTOR), {timeout: 15000})
        .toBeGreaterThan(before + 200);

    // a sensor block on a motor port names the port and stops the program
    await page.evaluate(m => {
        const stage = window.b3vm.runtime.getTargetForStage();
        stage.blocks.createBlock({id: 'bad',
            opcode: 'flippersensors_color',
            topLevel: true,
            parent: null,
            next: null,
            shadow: false,
            inputs: {},
            fields: {PORT: {name: 'PORT', value: m}}});
    }, MOTOR);
    await page.evaluate(() => window.b3vm.runtime.toggleScript('bad'));
    await expect(page.getByRole('alert')).toContainText(`Port ${MOTOR}: expected Color Sensor`);
});

test('light blocks reach the Light and the matrix', async ({page}) => {
    test.skip(!process.env.B3_LIGHT_PORTS, 'needs hatd --sim-devices with B3_LIGHT_PORTS="<light>,<matrix>"');
    const [light, matrix] = process.env.B3_LIGHT_PORTS.split(',');
    await login(page);
    await page.getByRole('button', {name: /Take control/}).click();
    await expect(page.getByText('You control the robot')).toBeVisible();
    await page.evaluate(({lightPort, matrixPort}) => {
        const stage = window.b3vm.runtime.getTargetForStage();
        const block = (id, opcode, fields, next = null, parent = null) => stage.blocks.createBlock({
            id, opcode, topLevel: !parent, parent, next, shadow: false, inputs: {}, fields});
        block('hat', 'flipperevents_whenProgramStarts', {}, 'l1');
        block('l1', 'b3light_setBrightness', {PORT: {name: 'PORT', value: lightPort}}, 'm1', 'hat');
        block('m1', 'flipperlight_lightColorMatrixImageOn',
            {PORT: {name: 'PORT', value: matrixPort}, PATTERN: {name: 'PATTERN', value: 'rrrrrrrrr'}}, null, 'l1');
        stage.blocks.createBlock({id: 'b',
            opcode: 'math_number',
            topLevel: false,
            parent: 'l1',
            shadow: true,
            inputs: {},
            fields: {NUM: {name: 'NUM', value: '60'}},
            next: null});
        stage.blocks.getBlock('l1').inputs.BRIGHTNESS = {name: 'BRIGHTNESS', block: 'b', shadow: 'b'};
    }, {lightPort: light, matrixPort: matrix});
    await page.getByTitle('Run').click();
    await expect.poll(() => page.evaluate(p => window.b3vm.b3hub.device(p).brightness, light)).toBe(60);
    await expect(page.getByRole('alert')).toHaveCount(0);
});

test('projects are saved on the robot, opened again and deleted', async ({page}) => {
    await login(page);
    const name = `e2e ${Date.now()}`;
    const title = page.getByPlaceholder('Project title here');
    await title.fill(name);
    await title.press('Enter');
    await page.keyboard.press('Control+s');
    await expect(page.getByText('Project saved.')).toBeVisible(); // saveSuccess alert text in src/lib/alerts/index.jsx
    const saved = (await (await page.request.get('/api/projects')).json()).find(p => p.name === name);
    expect(saved).toBeTruthy();

    // an unsaved change (a new block; Scratch does not count a title edit as a change)
    const hasExtraBlock = () => page.evaluate(() => Boolean(
        window.b3vm.runtime.getTargetForStage().blocks.getBlock('extra')));
    await page.evaluate(() => window.b3vm.runtime.getTargetForStage().blocks.createBlock({id: 'extra',
        opcode: 'flippersound_stopSound',
        topLevel: true,
        parent: null,
        next: null,
        shadow: false,
        inputs: {},
        fields: {}}));
    await page.getByRole('button', {name: 'File'}).click();
    await page.getByText('Open from robot…').click();
    const row = page.getByRole('listitem').filter({hasText: name});
    let asked = false;
    page.once('dialog', dialog => {
        asked = true;
        dialog.dismiss(); // keep the unsaved change
    });
    await row.getByRole('button', {name: 'Open'}).click();
    await expect.poll(() => asked).toBe(true);
    expect(await hasExtraBlock()).toBe(true);
    page.once('dialog', dialog => dialog.accept());
    await row.getByRole('button', {name: 'Open'}).click();
    await expect.poll(hasExtraBlock).toBe(false);
    await expect(title).toHaveValue(name);

    await page.getByRole('button', {name: 'File'}).click();
    await page.getByText('Open from robot…').click();
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('listitem').filter({hasText: name})
        .getByRole('button', {name: 'Delete'})
        .click();
    await expect(page.getByRole('listitem').filter({hasText: name})).toHaveCount(0);
    const left = (await (await page.request.get('/api/projects')).json()).find(p => p.name === name);
    expect(left).toBeUndefined();
});

test('a project sound plays on the robot', async ({page}) => {
    await login(page);
    await page.getByRole('button', {name: /Take control/}).click();
    await expect(page.getByText('You control the robot')).toBeVisible();
    await page.evaluate(() => {
        const stage = window.b3vm.runtime.getTargetForStage();
        stage.blocks.createBlock({id: 'hat',
            opcode: 'flipperevents_whenProgramStarts',
            topLevel: true,
            parent: null,
            next: 'play',
            shadow: false,
            inputs: {},
            fields: {}});
        stage.blocks.createBlock({id: 'play',
            opcode: 'flippersound_playSoundUntilDone',
            topLevel: false,
            parent: 'hat',
            next: null,
            shadow: false,
            inputs: {},
            fields: {SOUND: {name: 'SOUND', value: 'pop'}}});
    });
    await page.getByTitle('Run').click();
    await expect.poll(() => page.evaluate(() => window.b3vm.b3hub._sounds.size), {timeout: 10000}).toBe(1);
    await expect(page.getByRole('alert')).toHaveCount(0);
});

test('an ADPCM WAV sound is converted and plays on the robot', async ({page}) => {
    const adpcm = [...readFileSync(new URL('../fixtures/movie.wav', import.meta.url))]; // IMA ADPCM
    await login(page);
    await page.getByRole('button', {name: /Take control/}).click();
    await expect(page.getByText('You control the robot')).toBeVisible();
    await page.evaluate(async bytes => {
        const vm = window.b3vm;
        const storage = vm.runtime.storage;
        const asset = storage.createAsset(storage.AssetType.Sound, storage.DataFormat.WAV,
            Uint8Array.from(bytes), null, true);
        await vm.addSound({name: 'movie', dataFormat: 'wav', asset, md5: `${asset.assetId}.wav`},
            vm.runtime.getTargetForStage().id);
        const stage = vm.runtime.getTargetForStage();
        stage.blocks.createBlock({id: 'hat',
            opcode: 'flipperevents_whenProgramStarts',
            topLevel: true,
            parent: null,
            next: 'play',
            shadow: false,
            inputs: {},
            fields: {}});
        stage.blocks.createBlock({id: 'play',
            opcode: 'flippersound_playSoundUntilDone',
            topLevel: false,
            parent: 'hat',
            next: null,
            shadow: false,
            inputs: {},
            fields: {SOUND: {name: 'SOUND', value: 'movie'}}});
    }, adpcm);
    await page.getByTitle('Run').click();
    await expect.poll(() => page.evaluate(() => window.b3vm.b3hub._sounds.size), {timeout: 10000}).toBe(1);
    await expect(page.getByRole('alert')).toHaveCount(0);
});

test('saving twice quickly keeps one project on the robot', async ({page}) => {
    await login(page);
    const name = `e2e twice ${Date.now()}`;
    const title = page.getByPlaceholder('Project title here');
    await title.fill(name);
    await title.press('Enter');
    await page.keyboard.press('Control+s');
    await page.keyboard.press('Control+s');
    await expect(page.getByText('Project saved.')).toBeVisible();
    await page.waitForTimeout(500);
    const saved = (await (await page.request.get('/api/projects')).json()).filter(p => p.name === name);
    expect(saved).toHaveLength(1);
    await page.request.delete(`/api/projects/${saved[0].id}`);
});

const flyoutWidth = async page => {
    const box = await page.locator('.blocklyFlyout').first()
        .boundingBox();
    return Math.round(box.width);
};

test('the block palette can be dragged wider and keeps its width', async ({page}) => {
    await login(page);
    const separator = page.getByRole('separator', {name: 'Resize block palette'});
    const before = await flyoutWidth(page);
    expect(before).toBeGreaterThan(340); // wide enough for the widest Motors block
    const box = await separator.boundingBox();
    await page.mouse.move(box.x + (box.width / 2), box.y + 200);
    await page.mouse.down();
    await page.mouse.move(box.x + (box.width / 2) + 100, box.y + 200, {steps: 5});
    await page.mouse.up();
    await expect.poll(() => flyoutWidth(page)).toBe(before + 100);
    await page.reload();
    await page.waitForFunction(() => window.b3vm && window.b3vm.runtime.b3workspace);
    await expect.poll(() => flyoutWidth(page)).toBe(before + 100);
    await page.getByRole('separator', {name: 'Resize block palette'}).dblclick();
    await expect.poll(() => flyoutWidth(page)).toBe(before);
});
