import PropTypes from 'prop-types';
import React from 'react';
import Modal from '../../containers/modal.jsx';
import styles from './b3-project-library.css';

const projectShape = PropTypes.shape({
    id: PropTypes.string,
    name: PropTypes.string,
    modified: PropTypes.string
});

const ProjectRow = ({project, onDelete, onOpen}) => {
    const handleOpen = React.useCallback(() => onOpen(project), [onOpen, project]);
    const handleDelete = React.useCallback(() => onDelete(project), [onDelete, project]);
    return (
        <li className={styles.row}>
            <span className={styles.name}>{project.name}</span>
            <span className={styles.date}>{new Date(project.modified).toLocaleString()}</span>
            <button onClick={handleOpen}>{'Open'}</button>
            <button onClick={handleDelete}>{'Delete'}</button>
        </li>
    );
};

ProjectRow.propTypes = {
    project: projectShape.isRequired,
    onDelete: PropTypes.func.isRequired,
    onOpen: PropTypes.func.isRequired
};

const B3ProjectLibrary = ({error, projects, onClose, onDelete, onOpen}) => (
    <Modal
        className={styles.modal}
        contentLabel="Projects on the robot"
        id="b3ProjectLibrary"
        onRequestClose={onClose}
    >
        <div className={styles.body}>
            {error ? <div
                className={styles.error}
                role="alert"
            >{error}</div> : null}
            {projects === null ? <div>{'Loading…'}</div> : null}
            {projects && projects.length === 0 ? <div>{'No projects on the robot yet.'}</div> : null}
            {projects && projects.length > 0 ? (
                <ul className={styles.list}>
                    {projects.map(project => (
                        <ProjectRow
                            key={project.id}
                            project={project}
                            onDelete={onDelete}
                            onOpen={onOpen}
                        />
                    ))}
                </ul>
            ) : null}
        </div>
    </Modal>
);

B3ProjectLibrary.propTypes = {
    error: PropTypes.string,
    projects: PropTypes.arrayOf(projectShape),
    onClose: PropTypes.func.isRequired,
    onDelete: PropTypes.func.isRequired,
    onOpen: PropTypes.func.isRequired
};

export default B3ProjectLibrary;
