export default {
    testDir: '.',
    timeout: 60000,
    use: {baseURL: process.env.B3_URL || 'http://localhost:8080', headless: true}
};
