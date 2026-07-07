from typing import TypedDict
from typing import List, Optional


class UserData(TypedDict):
    # 用户 ID
    id: str
    # 用户昵称
    nickname: str
    # 用户个性签名
    description: Optional[str]
    # 用户头像 URL
    avatarUrl: str


class SubCommentData(TypedDict):
    # 二级评论日期
    date: str
    # 二级评论 ID
    id: str
    # 二级评论发送者信息
    sender: UserData
    # 二级评论内容
    content: str
    # 父评论 ID
    parentId: str


class CommentData(TypedDict):
    # 评论日期
    date: str
    # 评论 ID
    id: str
    # 评论发送者信息
    sender: UserData
    # 评论内容
    content: str
    # 二级评论列表
    subComments: List[SubCommentData]
    # 父内容 ID
    parentId: str


class VideoData(TypedDict):
    # 视频发布日期
    date: str
    # 视频页面 URL
    url: str
    # 视频标题
    title: Optional[str]
    # 视频 ID
    id: str
    # 视频封面 URL
    coverUrl: str
    # 视频文件 URL 列表
    mediaList: Optional[List[str]]
    # 视频作者信息
    author: UserData
    # 视频简介
    description: str
    # 视频评论列表
    comments: List[CommentData]


class NoteData(TypedDict):
    # 图文发布日期
    date: str
    # 图文 URL
    url: str
    # 图文标题
    title: Optional[str]
    # 图文 ID
    id: str
    # 图文视频 URL
    videoUrl: Optional[List[str]]
    # 图文图片列表
    imageList: Optional[List[str]]
    # 图文作者信息
    author: UserData
    # 图文内容
    content: str
    # 图文评论列表
    comments: List[CommentData]


class ReturnData(TypedDict):
    # 平台
    platform: str
    # 返回数据类型
    type: str
    # 耗时
    timeTook: float
    # 返回数据
    data: list[VideoData | NoteData]


class ReturnDataUser(TypedDict):
    # 平台
    platform: str
    # 用户（被判定为高危、需二次确认的账户）
    user: UserData
    # 耗时
    timeTook: float
    # 返回数据类型
    type: str
    # 该用户近 10 条帖子（多模态）
    data: list[VideoData | NoteData]

