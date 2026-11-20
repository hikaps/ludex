pragma Singleton
import QtQuick

QtObject {
    readonly property color bg: "#0e1014"
    readonly property color surface: "#151820"
    readonly property color surface2: "#1c212b"
    readonly property color surface3: "#262d3a"
    readonly property color border: "#2b3342"
    readonly property color text: "#eceef4"
    readonly property color muted: "#8d95a8"
    readonly property color accent: "#7b5cff"
    readonly property color accentHover: "#8e75ff"
    readonly property color accentDown: "#6847f0"
    readonly property color good: "#37d08a"
    readonly property color bad: "#ff6b6b"
    readonly property int radius: 8
    readonly property int gap: 12
    readonly property int body: 14
    readonly property int small: 12
    readonly property int title: 28
    readonly property string family: Qt.application.font.family

    // A deterministic dark tint per game, for covers that have no picture.
    function tint(seed, lightness) {
        return Qt.hsla((seed * 0.61803398875) % 1, 0.45, lightness, 1)
    }

    function initials(title) {
        var words = String(title).replace(/[^\p{L}\p{N} ]/gu, " ").split(" ").filter(function (w) { return w.length > 0 })
        if (words.length === 0) {
            return "?"
        }
        var first = Array.from(words[0])[0]
        var second = words.length > 1 ? Array.from(words[1])[0] : ""
        return (first + second).toUpperCase()
    }
}
