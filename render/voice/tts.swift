// Module 8 stand-in voice (copied from the render test). Stand-in for the ElevenLabs call: speaks a text with a macOS system voice and
// returns the audio plus the time each word starts, the same shape of answer the
// real voice gives (audio + timestamps). The system voices here send no timing
// marks, but they do call the delegate as each word begins; noting how much audio
// has been written at that moment gives the word's start (to within ~12 ms buffers).
// usage: swift tts.swift <text file> <out .caf> <out .json>
import AVFoundation
import Foundation

let args = CommandLine.arguments
let text = try! String(contentsOfFile: args[1], encoding: .utf8)
  .trimmingCharacters(in: .whitespacesAndNewlines)
let outAudio = URL(fileURLWithPath: args[2])
let outJSON = URL(fileURLWithPath: args[3])

let voice = AVSpeechSynthesisVoice(identifier: "com.apple.voice.compact.en-US.Samantha")
  ?? AVSpeechSynthesisVoice(language: "en-US")!
var frames: Int64 = 0
var marks: [[String: Int]] = []
class WordTimer: NSObject, AVSpeechSynthesizerDelegate {
  func speechSynthesizer(_ s: AVSpeechSynthesizer, willSpeakRangeOfSpeechString r: NSRange, utterance u: AVSpeechUtterance) {
    marks.append(["loc": r.location, "len": r.length, "offset": Int(frames)])
  }
}
let timer = WordTimer()
let synth = AVSpeechSynthesizer()
synth.delegate = timer
let utt = AVSpeechUtterance(string: text)
utt.voice = voice
utt.rate = AVSpeechUtteranceDefaultSpeechRate

var file: AVAudioFile?
var sampleRate = 0.0
var bytesPerFrame: UInt32 = 0
var lastBuffer = Date()
var started = false
var done = false

synth.write(utt, toBufferCallback: { buf in
  guard let pcm = buf as? AVAudioPCMBuffer else { return }
  if pcm.frameLength == 0 { done = true; return }
  if file == nil {
    sampleRate = pcm.format.sampleRate
    bytesPerFrame = pcm.format.streamDescription.pointee.mBytesPerFrame
    file = try! AVAudioFile(forWriting: outAudio, settings: pcm.format.settings,
                            commonFormat: pcm.format.commonFormat, interleaved: pcm.format.isInterleaved)
  }
  try! file!.write(from: pcm)
  frames += Int64(pcm.frameLength)
  started = true
  lastBuffer = Date()
})

let deadline = Date().addingTimeInterval(120)
while !done && Date() < deadline && !(started && Date().timeIntervalSince(lastBuffer) > 3) {
  RunLoop.main.run(until: Date().addingTimeInterval(0.01))
}
file = nil

let out: [String: Any] = [
  "voice": voice.name, "sampleRate": sampleRate, "frames": frames,
  "bytesPerFrame": bytesPerFrame, "marks": marks, "text": text,
]
try! JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted]).write(to: outJSON)
print("voice \(voice.name), \(Double(frames) / sampleRate) s, \(marks.count) word marks")
