// AGENT-CTX: next/jest creates a jest config that handles Next.js-specific transforms
// (SWC, CSS modules, image mocks, etc.). Do not replace with a manual babel-jest config.
const nextJest = require("next/jest");

const createJestConfig = nextJest({ dir: "./" });

module.exports = createJestConfig({
  // AGENT-CTX: jest.setup.ts runs after the test framework is installed.
  // It imports @testing-library/jest-dom to add matchers like toBeInTheDocument().
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  testEnvironment: "jest-environment-jsdom",
  testMatch: ["**/__tests__/**/*.test.{ts,tsx}"],
});
