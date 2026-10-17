import {newProjectId, projectName, listProjects, readProject, writeProject, deleteProject}
    from '../../../src/lib/b3-projects';
import reducer, {openB3Library, closeB3Library, requestB3Save} from '../../../src/reducers/b3-projects';

const answer = (status, body) => jest.fn(() => Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4))
}));

describe('B3 projects client', () => {
    test('ids are 32 hex characters', () => {
        expect(newProjectId(n => new Uint8Array(n).fill(171))).toBe('ab'.repeat(16));
        expect(newProjectId()).toMatch(/^[0-9a-f]{32}$/);
    });
    test('names are trimmed, shortened and never empty', () => {
        expect(projectName('  Robot 1 ')).toBe('Robot 1');
        expect(projectName('')).toBe('Untitled');
        expect(projectName('x'.repeat(150))).toHaveLength(100);
    });
    test('requests use the session cookie and the right methods', async () => {
        const fetchFn = answer(200, [{id: 'a', name: 'A', modified: 't'}]);
        expect(await listProjects(fetchFn)).toEqual([{id: 'a', name: 'A', modified: 't'}]);
        expect(fetchFn).toHaveBeenLastCalledWith('/api/projects', {credentials: 'same-origin'});
        await readProject('a', fetchFn);
        expect(fetchFn).toHaveBeenLastCalledWith('/api/projects/a', {credentials: 'same-origin'});
        const body = new Blob(['PK']);
        await writeProject('a', 'My robot & me', body, fetchFn);
        expect(fetchFn).toHaveBeenLastCalledWith('/api/projects/a?name=My%20robot%20%26%20me',
            {method: 'PUT', credentials: 'same-origin', body});
        await deleteProject('a', fetchFn);
        expect(fetchFn).toHaveBeenLastCalledWith('/api/projects/a', {method: 'DELETE', credentials: 'same-origin'});
    });
    test('errors carry hatd\'s message, or a generic one', async () => {
        await expect(writeProject('a', 'A', null, answer(401, {error: {code: 'unauthorized', message: 'Log in first'}})))
            .rejects.toThrow('Log in first');
        await expect(listProjects(answer(500, null))).rejects.toThrow('Request failed (500)');
        await expect(listProjects(() => Promise.reject(new TypeError('Failed to fetch'))))
            .rejects.toThrow('Failed to fetch');
    });
});

describe('B3 projects reducer', () => {
    test('opens, closes and counts save requests', () => {
        let state = reducer(void 0, {type: 'init'});
        expect(state).toEqual({libraryOpen: false, saveRequests: 0});
        state = reducer(state, openB3Library());
        expect(state.libraryOpen).toBe(true);
        state = reducer(state, closeB3Library());
        expect(state.libraryOpen).toBe(false);
        state = reducer(reducer(state, requestB3Save()), requestB3Save());
        expect(state.saveRequests).toBe(2);
    });
});
