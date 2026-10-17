const {test} = require('tap');
const M = require('../../src/extensions/b3/matrix');

test('patterns are 9 colour letters', t => {
    t.same(M.parsePattern('rrr kgk WWW'), ['red', 'red', 'red', 'black', 'green', 'black', 'white', 'white', 'white']);
    t.same(M.parsePattern('r,r,r,r,r,r,r,r,r'), Array(9).fill('red'));
    t.equal(M.parsePattern('rrrrrrrr'), null, '8 letters');
    t.equal(M.parsePattern('rrrrrrrrx'), null, 'unknown letter');
    t.end();
});

test('a shown pattern renders at full brightness; black is off', t => {
    const m = M.newMatrix();
    M.showPattern(m, M.parsePattern('rkrkrkrkr'));
    t.same(M.render(m)[0], ['red', 10]);
    t.same(M.render(m)[1], ['black', 0]);
    m.brightness = 50;
    t.same(M.render(m)[0], ['red', 5]);
    M.clear(m);
    t.same(M.render(m), Array(9).fill(['black', 0]));
    t.end();
});

test('setPixel is 1-based column, row and ignores what is out of range', t => {
    const m = M.newMatrix();
    t.ok(M.setPixel(m, 3, 1, 'blue', 70));
    t.same(M.render(m)[2], ['blue', 7]);
    t.ok(M.setPixel(m, 1, 3, 'green', 150), 'level clamped');
    t.same(M.render(m)[6], ['green', 10]);
    t.notOk(M.setPixel(m, 0, 1, 'red', 100));
    t.notOk(M.setPixel(m, 1, 4, 'red', 100));
    t.notOk(M.setPixel(m, 1, 1, 'purple', 100));
    t.end();
});

test('rotate turns the image; orientation turns only the display', t => {
    const m = M.newMatrix();
    M.setPixel(m, 1, 1, 'red', 100); // top-left
    M.rotate(m, 'clockwise');
    t.same(M.render(m)[2], ['red', 10], 'top-left -> top-right');
    M.rotate(m, 'counterclockwise');
    t.same(M.render(m)[0], ['red', 10], 'back');
    m.orientation = 'right';
    t.same(M.render(m)[2], ['red', 10]);
    t.equal(m.pixels[0].color, 'red', 'model unchanged');
    m.orientation = 'upsidedown';
    t.same(M.render(m)[8], ['red', 10]);
    m.orientation = 'left';
    t.same(M.render(m)[6], ['red', 10]);
    t.end();
});
