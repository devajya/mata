/**
 * Manual Jest mock for @xyflow/react.
 *
 * AGENT-CTX: React Flow requires a browser canvas and ResizeObserver which are
 * not available in jsdom. This mock replaces the library for all tests so that:
 *   1. EvidenceGraph renders without canvas errors
 *   2. ReactFlow renders node components (nodeTypes) with their data props, so
 *      EvidenceNode, GapNode, RootNode content is accessible to findByText etc.
 *   3. useNodesState / useEdgesState are real useState wrappers so state changes
 *      (gray-out, selection) flow through correctly in tests.
 *
 * AGENT-CTX: This file is auto-discovered by Jest via the __mocks__ directory
 * adjacent to node_modules. No moduleNameMapper entry needed — Jest resolves
 * manual mocks in __mocks__ automatically for scoped packages when automock=false
 * and jest.mock('@xyflow/react') is called, OR when moduleNameMapper is set.
 * We use moduleNameMapper in jest.config.js to guarantee resolution.
 */
import React from "react";

export const ReactFlow = ({
  children,
  nodes,
  nodeTypes,
  onNodeClick,
}: {
  children?: React.ReactNode;
  nodes?: Array<{ id: string; type: string; data: unknown }>;
  nodeTypes?: Record<string, React.ComponentType<{ data: unknown; selected?: boolean }>>;
  onNodeClick?: (event: React.MouseEvent, node: { id: string; data: unknown }) => void;
}) => (
  <div data-testid="react-flow">
    {children}
    {nodes?.map((node) => {
      const NodeComp = nodeTypes?.[node.type];
      if (!NodeComp) return null;
      return (
        <div
          key={node.id}
          data-node-id={node.id}
          onClick={(e) => onNodeClick?.(e, node)}
        >
          <NodeComp data={node.data} />
        </div>
      );
    })}
  </div>
);

export const Background = () => null;
export const Controls   = () => null;
export const Handle     = () => null;
export const Position   = { Left: "left", Right: "right", Top: "top", Bottom: "bottom" } as const;

export const useNodesState = (initial: unknown[]) => {
  const [nodes, setNodes] = React.useState(initial);
  return [nodes, setNodes, () => {}] as const;
};

export const useEdgesState = (initial: unknown[]) => {
  const [edges, setEdges] = React.useState(initial);
  return [edges, setEdges, () => {}] as const;
};
