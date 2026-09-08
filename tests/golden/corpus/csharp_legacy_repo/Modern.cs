using System;
using System.Collections.Generic;

public class Modern
{
    public void Collect()
    {
        var list = new List<string>();
        var map = new Dictionary<string, int>();
        var stack = new Stack<int>();
        Console.WriteLine(list.Count + map.Count + stack.Count);
    }
}
