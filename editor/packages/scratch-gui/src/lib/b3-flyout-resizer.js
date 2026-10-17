// B3: the block palette (flyout) has a fixed width in scratch-blocks, which cuts off the
// widest B3 blocks. A separator on its right edge lets the user drag it wider.

const MIN_WIDTH = 250; // scratch-blocks' own width
const MAX_WIDTH = 600;
const DEFAULT_WIDTH = 360; // the widest Motors block is about 346 px
const KEY_STEP = 20;
const STORAGE_KEY = 'b3.flyoutWidth';

const clampWidth = width => Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width)));

// Browser storage may be missing or blocked (private window); the width is only a convenience.
const loadWidth = () => {
    try {
        const stored = Number.parseInt(localStorage.getItem(STORAGE_KEY), 10);
        return Number.isFinite(stored) ? clampWidth(stored) : DEFAULT_WIDTH;
    } catch (e) {
        return DEFAULT_WIDTH;
    }
};

const saveWidth = width => {
    try {
        localStorage.setItem(STORAGE_KEY, String(width));
    } catch (e) {
        // not remembered; nothing else depends on it
    }
};

/**
 * Give the workspace's flyout a new width and lay out the flyout and the workspace again.
 * @param {object} workspace - the main Blockly workspace
 * @param {number} width - flyout width in pixels
 */
const applyFlyoutWidth = (workspace, width) => {
    const flyout = workspace.getFlyout();
    flyout.getWidth = () => width;
    flyout.width_ = width;
    flyout.position();
    workspace.resize();
};

/**
 * Add a draggable separator between the flyout and the workspace and apply the remembered width.
 * @param {object} workspace - the main Blockly workspace
 * @returns {Function} detach - removes the separator and its listeners
 */
const attachFlyoutResizer = workspace => {
    const toolbox = workspace.getToolbox();
    const toolboxWidth = () => (toolbox ? toolbox.getWidth() : 0);
    const handle = document.createElement('div');
    handle.className = 'b3FlyoutResizer';
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', 'vertical');
    handle.setAttribute('aria-label', 'Resize block palette');
    handle.setAttribute('aria-valuemin', String(MIN_WIDTH));
    handle.setAttribute('aria-valuemax', String(MAX_WIDTH));
    handle.title = 'Drag to resize, double-click to reset';
    handle.tabIndex = 0;

    let width = loadWidth();
    const setWidth = newWidth => {
        width = clampWidth(newWidth);
        applyFlyoutWidth(workspace, width);
        handle.style.left = `${toolboxWidth() + width}px`;
        handle.setAttribute('aria-valuenow', String(width));
    };

    let drag = null; // {startX, startWidth} while dragging
    const onMove = e => {
        if (drag) setWidth(drag.startWidth + (e.clientX - drag.startX));
    };
    const onUp = e => {
        if (!drag) return;
        onMove(e);
        drag = null;
        document.body.classList.remove('b3FlyoutResizing');
        saveWidth(width);
    };
    const onDown = e => {
        if (e.button !== 0) return;
        e.preventDefault();
        drag = {startX: e.clientX, startWidth: width};
        document.body.classList.add('b3FlyoutResizing');
    };
    const onDoubleClick = () => {
        setWidth(DEFAULT_WIDTH);
        saveWidth(width);
    };
    const onKey = e => {
        const step = {ArrowLeft: -KEY_STEP, ArrowRight: KEY_STEP}[e.key];
        if (!step) return;
        e.preventDefault();
        setWidth(width + step);
        saveWidth(width);
    };

    handle.addEventListener('pointerdown', onDown);
    handle.addEventListener('dblclick', onDoubleClick);
    handle.addEventListener('keydown', onKey);
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onUp);
    workspace.getInjectionDiv().appendChild(handle);
    setWidth(width);

    return () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        document.removeEventListener('pointercancel', onUp);
        document.body.classList.remove('b3FlyoutResizing');
        handle.remove();
    };
};

export {
    DEFAULT_WIDTH,
    MAX_WIDTH,
    MIN_WIDTH,
    STORAGE_KEY,
    applyFlyoutWidth,
    attachFlyoutResizer,
    clampWidth,
    loadWidth
};
