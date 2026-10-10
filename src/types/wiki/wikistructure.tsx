import { WikiPage } from "./wikipage";

/**
 * @fileoverview This file defines the structure of a wiki page and its sections.
 *
 * WikiStructure / WikiSection 的权威定义已收敛到 ./wikipage.tsx，
 * 此处保留再导出以兼容既有引用。
 */
export interface WikiStructure {
    id: string;
    title: string;
    description: string;
    pages: WikiPage[];
}

export type { WikiPage } from "./wikipage";
