import PropTypes from 'prop-types';
import React from 'react';
import B3BarComponent from '../components/b3-bar/b3-bar.jsx';

const snapshot = hub => ({
    state: hub.state,
    isController: hub.isController,
    hasController: hub.holder !== null,
    ports: hub.ports,
    vin: hub.vin,
    running: hub.running
});

class B3Bar extends React.Component {
    constructor (props) {
        super(props);
        this.hub = props.vm.b3hub;
        this.state = {...snapshot(this.hub), error: null, pinError: null};
        this.refresh = () => this.setState(snapshot(this.hub));
        this.onBlockError = e => {
            this.setState({error: e.message});
            const workspace = this.props.vm.runtime && this.props.vm.runtime.b3workspace;
            if (workspace && e.blockId) {
                const block = workspace.getBlockById(e.blockId);
                if (block) {
                    block.select();
                    workspace.centerOnBlock(e.blockId);
                }
            }
        };
        this.handleRun = () => this.props.vm.greenFlag();
        this.handleStop = () => this.props.vm.stopAll();
        this.handleTakeControl = () => this.hub.claimControl().catch(e => this.setState({error: e.message}));
        this.handleLogin = pin => this.hub.login(pin)
            .then(() => this.setState({pinError: null}))
            .catch(e => this.setState({pinError: e.message}));
        this.handleDismissError = () => this.setState({error: null});
    }

    componentDidMount () {
        for (const name of ['state', 'telemetry', 'control', 'running']) this.hub.on(name, this.refresh);
        this.hub.on('blockError', this.onBlockError);
        this.hub.start();
    }

    componentWillUnmount () {
        for (const name of ['state', 'telemetry', 'control', 'running']) this.hub.removeListener(name, this.refresh);
        this.hub.removeListener('blockError', this.onBlockError);
    }

    render () {
        return (
            <B3BarComponent
                {...this.state}
                onDismissError={this.handleDismissError}
                onLogin={this.handleLogin}
                onRun={this.handleRun}
                onStop={this.handleStop}
                onTakeControl={this.handleTakeControl}
            />
        );
    }
}

B3Bar.propTypes = {
    vm: PropTypes.shape({
        b3hub: PropTypes.object, // eslint-disable-line react/forbid-prop-types
        greenFlag: PropTypes.func,
        stopAll: PropTypes.func,
        runtime: PropTypes.object // eslint-disable-line react/forbid-prop-types
    }).isRequired
};

export default B3Bar;
