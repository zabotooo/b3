const OPEN_LIBRARY = 'scratch-gui/b3-projects/OPEN_LIBRARY';
const CLOSE_LIBRARY = 'scratch-gui/b3-projects/CLOSE_LIBRARY';
const REQUEST_SAVE = 'scratch-gui/b3-projects/REQUEST_SAVE';

const initialState = {libraryOpen: false, saveRequests: 0};

const reducer = function (state, action) {
    if (typeof state === 'undefined') state = initialState;
    switch (action.type) {
    case OPEN_LIBRARY:
        return {...state, libraryOpen: true};
    case CLOSE_LIBRARY:
        return {...state, libraryOpen: false};
    case REQUEST_SAVE:
        return {...state, saveRequests: state.saveRequests + 1};
    default:
        return state;
    }
};

const openB3Library = () => ({type: OPEN_LIBRARY});
const closeB3Library = () => ({type: CLOSE_LIBRARY});
const requestB3Save = () => ({type: REQUEST_SAVE});

export {reducer as default, initialState as b3ProjectsInitialState, openB3Library, closeB3Library, requestB3Save};
