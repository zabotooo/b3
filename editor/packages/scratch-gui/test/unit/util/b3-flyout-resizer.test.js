import {
    DEFAULT_WIDTH, MAX_WIDTH, MIN_WIDTH, STORAGE_KEY,
    applyFlyoutWidth, attachFlyoutResizer, clampWidth, loadWidth
} from '../../../src/lib/b3-flyout-resizer';

const fakeWorkspace = () => {
    const injectionDiv = document.createElement('div');
    document.body.appendChild(injectionDiv);
    const flyout = {getWidth: () => 250, position: jest.fn()};
    return {
        flyout,
        injectionDiv,
        resize: jest.fn(),
        getFlyout: () => flyout,
        getToolbox: () => ({getWidth: () => 60}),
        getInjectionDiv: () => injectionDiv
    };
};

const pointer = (target, type, clientX) => {
    target.dispatchEvent(new MouseEvent(type, {bubbles: true, clientX, button: 0}));
};

beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '';
});

describe('B3 flyout width', () => {
    test('is kept between the smallest and the largest width', () => {
        expect(clampWidth(100)).toBe(MIN_WIDTH);
        expect(clampWidth(5000)).toBe(MAX_WIDTH);
        expect(clampWidth(333.4)).toBe(333);
    });

    test('starts at the default unless a valid width was stored', () => {
        expect(loadWidth()).toBe(DEFAULT_WIDTH);
        localStorage.setItem(STORAGE_KEY, 'wide');
        expect(loadWidth()).toBe(DEFAULT_WIDTH);
        localStorage.setItem(STORAGE_KEY, '420');
        expect(loadWidth()).toBe(420);
        localStorage.setItem(STORAGE_KEY, '9999');
        expect(loadWidth()).toBe(MAX_WIDTH);
    });

    test('applying a width redraws the flyout and the workspace', () => {
        const ws = fakeWorkspace();
        applyFlyoutWidth(ws, 400);
        expect(ws.flyout.getWidth()).toBe(400);
        expect(ws.flyout.position).toHaveBeenCalled();
        expect(ws.resize).toHaveBeenCalled();
    });
});

describe('B3 flyout resizer', () => {
    test('puts a separator on the edge between the flyout and the workspace', () => {
        const ws = fakeWorkspace();
        attachFlyoutResizer(ws);
        const handle = ws.injectionDiv.querySelector('[role="separator"]');
        expect(handle).not.toBeNull();
        expect(handle.getAttribute('aria-orientation')).toBe('vertical');
        expect(handle.style.left).toBe(`${60 + DEFAULT_WIDTH}px`);
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH);
    });

    test('dragging the separator resizes the flyout and remembers the width', () => {
        const ws = fakeWorkspace();
        attachFlyoutResizer(ws);
        const handle = ws.injectionDiv.querySelector('[role="separator"]');
        pointer(handle, 'pointerdown', 400);
        pointer(document, 'pointermove', 480);
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH + 80);
        expect(handle.style.left).toBe(`${60 + DEFAULT_WIDTH + 80}px`);
        pointer(document, 'pointermove', -1000);
        expect(ws.flyout.getWidth()).toBe(MIN_WIDTH);
        pointer(document, 'pointerup', -1000);
        expect(localStorage.getItem(STORAGE_KEY)).toBe(String(MIN_WIDTH));
        pointer(document, 'pointermove', 900);
        expect(ws.flyout.getWidth()).toBe(MIN_WIDTH, 'no resizing after the drag ended');
    });

    test('a double click restores the default width', () => {
        const ws = fakeWorkspace();
        localStorage.setItem(STORAGE_KEY, '500');
        attachFlyoutResizer(ws);
        expect(ws.flyout.getWidth()).toBe(500);
        ws.injectionDiv.querySelector('[role="separator"]').dispatchEvent(new MouseEvent('dblclick'));
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH);
        expect(localStorage.getItem(STORAGE_KEY)).toBe(String(DEFAULT_WIDTH));
    });

    test('arrow keys move the separator', () => {
        const ws = fakeWorkspace();
        attachFlyoutResizer(ws);
        const handle = ws.injectionDiv.querySelector('[role="separator"]');
        expect(handle.tabIndex).toBe(0);
        handle.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'}));
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH + 20);
        handle.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft'}));
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH);
    });

    test('a broken storage does not stop the editor', () => {
        const getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        const ws = fakeWorkspace();
        attachFlyoutResizer(ws);
        const handle = ws.injectionDiv.querySelector('[role="separator"]');
        pointer(handle, 'pointerdown', 0);
        pointer(document, 'pointerup', 10);
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH + 10);
        getItem.mockRestore();
        setItem.mockRestore();
    });

    test('detaching removes the separator and its listeners', () => {
        const ws = fakeWorkspace();
        const detach = attachFlyoutResizer(ws);
        const handle = ws.injectionDiv.querySelector('[role="separator"]');
        pointer(handle, 'pointerdown', 0);
        detach();
        expect(ws.injectionDiv.querySelector('[role="separator"]')).toBeNull();
        pointer(document, 'pointermove', 100);
        expect(ws.flyout.getWidth()).toBe(DEFAULT_WIDTH);
    });
});
