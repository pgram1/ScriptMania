#Requires AutoHotkey v2.0

global isPasting := false

^+v::
{
    global isPasting
    if (isPasting)
        return
        
    ; 2-second countdown delay
    Sleep 2000
    
    clipText := A_Clipboard
    if (clipText != "") {
        isPasting := true
        
        Loop Parse, clipText {
            if (!isPasting) {
                CleanUpAndAbort()
                return
            }
            
            SendEvent "{Raw}" A_LoopField
            Sleep 15 
        }
        
        isPasting := false
    }
}

; Press Escape to stop typing immediately
~Esc::
{
    global isPasting
    if (isPasting) {
        isPasting := false
    }
}

; Clean up stuck keys instantly on abort
CleanUpAndAbort()
{
    Critical ; Prevents the script from being interrupted during cleanup
    
    ; Force Windows to release any stuck modifier keys
    Send "{Ctrl Up}{Shift Up}{Alt Up}{LWin Up}{RWin Up}"
    
    Tooltip "Paste Aborted (Keys Reset)"
    SetTimer () => Tooltip(), -1500
}
