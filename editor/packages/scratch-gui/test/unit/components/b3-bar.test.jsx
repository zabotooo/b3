import React from 'react';
import {render, screen} from '@testing-library/react';
import '@testing-library/jest-dom';
import B3BarComponent from '../../../src/components/b3-bar/b3-bar.jsx';

const props = over => ({
    state: 'connected',
    isController: false,
    hasController: false,
    ports: {A: null, B: null, C: null, D: null},
    vin: 8,
    onDismissError: jest.fn(),
    onLogin: jest.fn(),
    onRun: jest.fn(),
    onStop: jest.fn(),
    onTakeControl: jest.fn(),
    ...over
});

describe('B3 bar', () => {
    test('Run explains why it is disabled', () => {
        render(<B3BarComponent {...props()} />);
        expect(screen.getByTitle('Take control first')).toBeDisabled();
    });
    test('Run is enabled for the controller', () => {
        render(<B3BarComponent {...props({isController: true})} />);
        expect(screen.getByTitle('Run')).toBeEnabled();
    });
    test('an incompatible robot asks to reload the page', () => {
        render(<B3BarComponent {...props({state: 'incompatible'})} />);
        expect(screen.getByText('B3 on the robot was updated. Reload this page.')).toBeInTheDocument();
    });
});
