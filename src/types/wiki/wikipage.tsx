// Wiki Interfaces —— 前端 Wiki 数据契约的唯一权威定义
// 与后端 api/models.py 的 WikiPage / WikiSection / WikiStructureModel 严格对齐。
// 各页面组件（page.tsx / WikiTreeView / slides / workshop）统一从此处导入，
// 避免多份内联重复声明导致契约漂移。

export interface WikiPage {
  id: string;
  title: string;
  content: string;
  filePaths: string[];
  importance: 'high' | 'medium' | 'low';
  relatedPages: string[];
  // 树定位字段：标识该页面在目录树中的位置
  parentId?: string;      // 所属父节点（section 或父 page）的 id
  isSection?: boolean;    // 是否本身是一个 section 节点
  children?: string[];    // 子节点（page 或 section）的 id 列表
}

export interface WikiSection {
  id: string;
  title: string;
  pages: string[];
  subsections?: string[];
}

export interface WikiStructure {
  id: string;
  title: string;
  description: string;
  pages: WikiPage[];
  sections: WikiSection[];
  rootSections: string[];
}
