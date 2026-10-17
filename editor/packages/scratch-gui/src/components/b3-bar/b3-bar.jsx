import PropTypes from 'prop-types';
import React from 'react';
import describePort, {LOW_VIN} from './describe-port';
import styles from './b3-bar.css';

const STATUS = {
    'idle': 'Connecting…',
    'connecting': 'Connecting…',
    'connected': 'Connected',
    'need-pin': 'PIN required',
    'disconnected': 'Disconnected — reconnecting…',
    'incompatible': 'B3 on the robot was updated. Reload this page.'
};

const PinDialog = ({onLogin, pinError}) => {
    const [pin, setPin] = React.useState('');
    const handleSubmit = React.useCallback(e => {
        e.preventDefault();
        onLogin(pin);
    }, [onLogin, pin]);
    const handleChange = React.useCallback(e => setPin(e.target.value), []);
    return (
        <form
            className={styles.pinDialog}
            onSubmit={handleSubmit}
        >
            <label htmlFor="b3-pin">{'Robot PIN'}</label>
            <input
                autoFocus
                id="b3-pin"
                inputMode="numeric"
                type="password"
                value={pin}
                onChange={handleChange}
            />
            <button type="submit">{'Connect'}</button>
            {pinError ? <div className={styles.pinError}>{pinError}</div> : null}
        </form>
    );
};
PinDialog.propTypes = {onLogin: PropTypes.func.isRequired, pinError: PropTypes.string};

const B3BarComponent = props => {
    const connected = props.state === 'connected';
    return (
        <div className={styles.bar}>
            <div className={styles.row}>
                <button
                    className={styles.run}
                    disabled={!connected || !props.isController}
                    title={connected && !props.isController ? 'Take control first' : 'Run'}
                    onClick={props.onRun}
                >{'▶'}</button>
                <button
                    className={styles.stop}
                    title="Stop"
                    onClick={props.onStop}
                >{'■'}</button>
                <span className={styles.status}>{STATUS[props.state] || props.state}</span>
                {connected && props.isController ? (
                    <span className={styles.control}>{'You control the robot'}</span>
                ) : null}
                {connected && !props.isController ? (
                    <button
                        className={styles.take}
                        onClick={props.onTakeControl}
                    >{props.hasController ? 'Take control (stops the robot)' : 'Take control'}</button>
                ) : null}
            </div>
            {connected ? (
                <div className={styles.ports}>
                    {['A', 'B', 'C', 'D'].map(port => {
                        const {title, value} = describePort(port, props.ports[port]);
                        return (
                            <div
                                className={styles.port}
                                key={port}
                            >
                                <div className={styles.portTitle}>{title}</div>
                                <div className={styles.portValue}>{value}</div>
                            </div>
                        );
                    })}
                    {props.vin !== null && props.vin < LOW_VIN ? (
                        <div className={styles.warning}>{'Motors need external power'}</div>
                    ) : null}
                </div>
            ) : null}
            {props.state === 'need-pin' ? (
                <PinDialog
                    pinError={props.pinError}
                    onLogin={props.onLogin}
                />
            ) : null}
            {props.error ? (
                <div
                    className={styles.error}
                    role="alert"
                >
                    <span>{props.error}</span>
                    <button onClick={props.onDismissError}>{'×'}</button>
                </div>
            ) : null}
        </div>
    );
};

B3BarComponent.propTypes = {
    error: PropTypes.string,
    hasController: PropTypes.bool,
    isController: PropTypes.bool,
    onDismissError: PropTypes.func.isRequired,
    onLogin: PropTypes.func.isRequired,
    onRun: PropTypes.func.isRequired,
    onStop: PropTypes.func.isRequired,
    onTakeControl: PropTypes.func.isRequired,
    pinError: PropTypes.string,
    ports: PropTypes.object, // eslint-disable-line react/forbid-prop-types
    state: PropTypes.string.isRequired,
    vin: PropTypes.number
};

export default B3BarComponent;
