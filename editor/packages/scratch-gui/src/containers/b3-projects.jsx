import PropTypes from 'prop-types';
import React from 'react';
import {connect} from 'react-redux';
import B3ProjectLibrary from '../components/b3-project-library/b3-project-library.jsx';
import {closeB3Library} from '../reducers/b3-projects';
import {setProjectTitle} from '../reducers/project-title';
import {setProjectUnchanged} from '../reducers/project-changed';
import {showAlertWithTimeout, showStandardAlert} from '../reducers/alerts';
import {deleteProject, listProjects, newProjectId, projectName, readProject, writeProject}
    from '../lib/b3-projects';

/** Save, open and delete projects on the Pi. Which robot project is open lives here. */
class B3Projects extends React.Component {
    constructor (props) {
        super(props);
        this.state = {projects: null, error: null};
        this.projectId = null; // id on the Pi of the open project; null until saved or opened
        this.openingId = null;
        this.handleProjectLoaded = () => {
            this.projectId = this.openingId; // New and "Load from your computer" clear it
            this.openingId = null;
        };
        this.handleOpen = project => this.open(project);
        this.handleDelete = project => this.remove(project);
    }

    componentDidMount () {
        this.props.vm.runtime.on('PROJECT_LOADED', this.handleProjectLoaded);
    }

    componentDidUpdate (prevProps) {
        if (this.props.saveRequests !== prevProps.saveRequests) this.save();
        if (this.props.libraryOpen && !prevProps.libraryOpen) this.refresh();
    }

    componentWillUnmount () {
        this.props.vm.runtime.removeListener('PROJECT_LOADED', this.handleProjectLoaded);
    }

    refresh () {
        this.setState({projects: null, error: null});
        return listProjects().then(projects => this.setState({projects}), e => this.setState({error: e.message}));
    }

    async save () {
        // Kept before the first await: a second save started meanwhile (Ctrl+S twice) must
        // write the same project, not create another one.
        if (!this.projectId) this.projectId = newProjectId();
        const id = this.projectId;
        this.props.onSaving();
        try {
            const sb3 = await this.props.vm.saveProjectSb3();
            await writeProject(id, projectName(this.props.projectTitle), sb3);
            this.props.onSaved();
        } catch (e) {
            this.props.onSaveFailed();
        }
    }

    async open (project) {
        const replace = 'Replace the current project? Unsaved changes will be lost.';
        if (this.props.projectChanged && !window.confirm(replace)) return; // eslint-disable-line no-alert
        try {
            const data = await readProject(project.id);
            this.openingId = project.id;
            await this.props.vm.loadProject(data);
            this.props.onOpened(project.name);
        } catch (e) {
            this.openingId = null;
            this.setState({error: e.message});
        }
    }

    async remove (project) {
        if (!window.confirm(`Delete "${project.name}" from the robot?`)) return; // eslint-disable-line no-alert
        try {
            await deleteProject(project.id);
            if (project.id === this.projectId) this.projectId = null;
            await this.refresh();
        } catch (e) {
            this.setState({error: e.message});
        }
    }

    render () {
        if (!this.props.libraryOpen) return null;
        return (
            <B3ProjectLibrary
                error={this.state.error}
                projects={this.state.projects}
                onClose={this.props.onClose}
                onDelete={this.handleDelete}
                onOpen={this.handleOpen}
            />
        );
    }
}

B3Projects.propTypes = {
    libraryOpen: PropTypes.bool,
    projectChanged: PropTypes.bool,
    projectTitle: PropTypes.string,
    saveRequests: PropTypes.number,
    vm: PropTypes.shape({
        loadProject: PropTypes.func,
        saveProjectSb3: PropTypes.func,
        runtime: PropTypes.object // eslint-disable-line react/forbid-prop-types
    }).isRequired,
    onClose: PropTypes.func.isRequired,
    onOpened: PropTypes.func.isRequired,
    onSaveFailed: PropTypes.func.isRequired,
    onSaved: PropTypes.func.isRequired,
    onSaving: PropTypes.func.isRequired
};

const mapStateToProps = state => ({
    libraryOpen: state.scratchGui.b3Projects.libraryOpen,
    saveRequests: state.scratchGui.b3Projects.saveRequests,
    projectChanged: state.scratchGui.projectChanged,
    projectTitle: state.scratchGui.projectTitle
});

const mapDispatchToProps = dispatch => ({
    onClose: () => dispatch(closeB3Library()),
    onOpened: name => {
        dispatch(setProjectTitle(name));
        dispatch(setProjectUnchanged());
        dispatch(closeB3Library());
    },
    onSaving: () => dispatch(showStandardAlert('b3Saving')),
    onSaved: () => {
        dispatch(setProjectUnchanged());
        showAlertWithTimeout(dispatch, 'b3Saved'); // replaces b3Saving
    },
    onSaveFailed: () => dispatch(showStandardAlert('b3SaveError'))
});

export default connect(mapStateToProps, mapDispatchToProps)(B3Projects);
