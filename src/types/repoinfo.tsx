export interface RepoInfo {
    projectId: string | null;
    owner: string;
    repo: string;
    type: string;
    token: string | null;
    localPath: string | null;
    repoUrl: string | null;
}

export default RepoInfo;