// Projects stored on the Pi by hatd (same origin as the editor; session cookie).

const check = async resp => {
    if (resp.ok) return resp;
    const body = await resp.json().catch(() => null);
    throw new Error((body && body.error && body.error.message) || `Request failed (${resp.status})`);
};

const randomBytes = n => crypto.getRandomValues(new Uint8Array(n));

export const newProjectId = (random = randomBytes) =>
    Array.from(random(16), b => b.toString(16).padStart(2, '0')).join('');

export const projectName = title => (title || '').trim()
    .slice(0, 100) || 'Untitled';

export const listProjects = (fetchFn = fetch) =>
    fetchFn('/api/projects', {credentials: 'same-origin'}).then(check)
        .then(resp => resp.json());

export const readProject = (id, fetchFn = fetch) =>
    fetchFn(`/api/projects/${id}`, {credentials: 'same-origin'}).then(check)
        .then(resp => resp.arrayBuffer());

export const writeProject = (id, name, body, fetchFn = fetch) =>
    fetchFn(`/api/projects/${id}?name=${encodeURIComponent(name)}`, {method: 'PUT', credentials: 'same-origin', body})
        .then(check)
        .then(resp => resp.json());

export const deleteProject = (id, fetchFn = fetch) =>
    fetchFn(`/api/projects/${id}`, {method: 'DELETE', credentials: 'same-origin'}).then(check);
