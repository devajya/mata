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
  moduleNameMapper: {
    // AGENT-CTX: @xyflow/react requires a browser canvas (ResizeObserver, SVG transforms)
    // not available in jsdom. The manual mock in __mocks__/@xyflow/react.tsx replaces
    // the library for all tests, rendering node components into plain divs so that
    // findByText / getByText assertions on EvidenceNode content still work.
    "^@xyflow/react$": "<rootDir>/__mocks__/@xyflow/react.tsx",
    // AGENT-CTX: @xyflow/react CSS import in layout.tsx — map to identity mock
    // to prevent "CSS Module not supported" errors in test environment.
    "^@xyflow/react/dist/style\\.css$": "<rootDir>/__mocks__/styleMock.js",
  },
});
