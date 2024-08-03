import messageRepository from "../../storage/messageRepository"


export default async (req, res) => {
    const _ = await messageRepository.ping();
    return res.status(200).json({ status: 'Healthy' })
}